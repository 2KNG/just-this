#!/usr/bin/env python3
"""
webcrop — 스캔/이미지 문서를 자르고(crop) 회전(rotate)하고 변환(convert)하는 웹앱.

흐름
  1) 업로드: PDF/PNG/JPG → 서버가 orient(90/180/270)/자동 deskew/미세회전 적용 → 보정본 미리보기
  2) crop  : 브라우저 Cropper.js로 페이지별 박스 (용지 비율 고정 가능)
  3) 변환  : crop + 용지규격 + 출력포맷 적용 → PDF/PNG/JPG 다운로드 (여러 장은 zip)

좌표 안 꼬이게: orient/deskew/회전은 업로드 때 서버가 적용해 '보정된 미리보기'를 만들고,
crop은 그 보정본 위에서 픽셀 좌표로 잡는다. 변환도 같은 보정본을 잘라 일치.

단일 프로세스로 실행 (run.py가 그렇게 띄움). 세션은 임시폴더에 저장, 30분 TTL.
"""

import io
import json
import os
import shutil
import tempfile
import time
import uuid
import zipfile

import cv2
import fitz  # PyMuPDF
import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

MAX_UPLOAD_MB = 50
SESSION_TTL_SEC = 60 * 30
RENDER_DPI = 300  # PDF 렌더 해상도. 이미지 입력은 원본 해상도 그대로 사용.
HERE = os.path.dirname(os.path.abspath(__file__))
TMP_ROOT = os.path.join(tempfile.gettempdir(), "webcrop_sessions")
os.makedirs(TMP_ROOT, exist_ok=True)

PAPER_SIZES_MM = {
    "a3": (297, 420), "a4": (210, 297), "a5": (148, 210),
    "letter": (215.9, 279.4), "legal": (215.9, 355.6), "tabloid": (279.4, 431.8),
    "card": (90, 50), "card_us": (88.9, 50.8),
}

SESSIONS = {}  # token -> {"dir": path, "files": [fn...], "ts": time}

app = FastAPI(title="webcrop")
app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")


# ---------------- 이미지 처리 ----------------
def pdf_or_image_to_images(data, ext, dpi):
    if ext == ".pdf":
        doc = fitz.open(stream=data, filetype="pdf")
        out = []
        mat = fitz.Matrix(dpi / 72.0, dpi / 72.0)
        for page in doc:
            pix = page.get_pixmap(matrix=mat, alpha=False)
            arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
            out.append(cv2.cvtColor(arr, cv2.COLOR_RGB2BGR))
        doc.close()
        return out
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(400, "이미지를 디코드할 수 없음")
    return [img]


def detect_skew_angle(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    coords = np.column_stack(np.where(thresh > 0))
    if len(coords) < 50:
        return 0.0
    angle = cv2.minAreaRect(coords)[-1]
    if angle < -45:
        angle = 90 + angle
    elif angle > 45:
        angle = angle - 90
    return 0.0 if abs(angle) > 20 else float(angle)


def rotate_image(img, angle):
    if abs(angle) < 0.01:
        return img
    h, w = img.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_CUBIC,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255))


def orient_image(img, orient):
    orient %= 360
    if orient == 90:
        return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    if orient == 180:
        return cv2.rotate(img, cv2.ROTATE_180)
    if orient == 270:
        return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return img


def paper_ratio(paper, landscape):
    mm_w, mm_h = PAPER_SIZES_MM[paper]
    if landscape:
        mm_w, mm_h = mm_h, mm_w
    return mm_w / mm_h


def fit_paper_crop(img, paper, landscape):
    target = paper_ratio(paper, landscape)
    h, w = img.shape[:2]
    if w / h > target:
        new_w = int(h * target)
        x0 = (w - new_w) // 2
        return img[:, x0:x0 + new_w]
    new_h = int(w / target)
    y0 = (h - new_h) // 2
    return img[y0:y0 + new_h, :]


def fit_paper_canvas(img, paper, landscape):
    target = paper_ratio(paper, landscape)
    h, w = img.shape[:2]
    if w / h > target:
        cw, ch = w, int(round(w / target))
    else:
        ch, cw = h, int(round(h * target))
    canvas = np.full((ch, cw, 3), 255, dtype=np.uint8)
    canvas[(ch - h) // 2:(ch - h) // 2 + h, (cw - w) // 2:(cw - w) // 2 + w] = img
    return canvas


# ---------------- 세션 ----------------
def cleanup_sessions():
    now = time.time()
    for token in list(SESSIONS.keys()):
        if now - SESSIONS[token]["ts"] > SESSION_TTL_SEC:
            shutil.rmtree(SESSIONS[token]["dir"], ignore_errors=True)
            SESSIONS.pop(token, None)


def get_session(token):
    s = SESSIONS.get(token)
    if not s:
        raise HTTPException(404, "세션을 찾을 수 없음 (만료됐을 수 있음). 다시 올려주세요.")
    return s


# ---------------- 라우트 ----------------
@app.get("/", response_class=HTMLResponse)
def index():
    with open(os.path.join(HERE, "static", "index.html"), encoding="utf-8") as f:
        return f.read()


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.post("/api/upload")
async def upload(
    file: UploadFile = File(...),
    auto_deskew: bool = Form(True),
    rotate: float = Form(0.0),
    orient: int = Form(0),
):
    cleanup_sessions()
    data = await file.read()
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"파일이 너무 큼 (최대 {MAX_UPLOAD_MB}MB)")

    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in (".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"):
        raise HTTPException(400, f"지원하지 않는 포맷: {ext}")

    images = pdf_or_image_to_images(data, ext, RENDER_DPI)
    token = uuid.uuid4().hex
    sdir = os.path.join(TMP_ROOT, token)
    os.makedirs(sdir, exist_ok=True)

    pages, files = [], []
    for i, img in enumerate(images):
        if orient:
            img = orient_image(img, orient)
        if auto_deskew:
            ang = detect_skew_angle(img)
            if abs(ang) > 0.05:
                img = rotate_image(img, ang)
        if rotate:
            img = rotate_image(img, rotate)
        fn = f"page_{i:03d}.png"
        cv2.imwrite(os.path.join(sdir, fn), img)
        h, w = img.shape[:2]
        files.append(fn)
        # 상대경로 — 허브에 /webcrop 로 마운트돼도 동작
        pages.append({"idx": i, "w": int(w), "h": int(h), "url": f"api/preview/{token}/{i}"})

    SESSIONS[token] = {"dir": sdir, "files": files, "ts": time.time()}
    return {"token": token, "pages": pages}


@app.get("/api/preview/{token}/{idx}")
def preview(token: str, idx: int):
    s = get_session(token)
    if idx < 0 or idx >= len(s["files"]):
        raise HTTPException(404, "페이지 없음")
    return FileResponse(os.path.join(s["dir"], s["files"][idx]), media_type="image/png")


@app.post("/api/convert")
async def convert(
    token: str = Form(...),
    fmt: str = Form("pdf"),            # pdf | png | jpg
    paper: str = Form(""),            # "" 또는 a4/letter/...
    paper_mode: str = Form("crop"),   # crop | fit
    landscape: bool = Form(False),
    lossless: bool = Form(True),      # 기본 무손실: 크롭한 픽셀을 그대로 보존
    quality: int = Form(95),          # lossless=false 일 때만 사용 (JPEG 품질)
    dpi: int = Form(RENDER_DPI),
    crops: str = Form(""),            # JSON: [{"idx":0,"x":..,"y":..,"w":..,"h":..}, ...] (픽셀)
):
    s = get_session(token)
    s["ts"] = time.time()

    crop_map = {}
    if crops:
        try:
            for c in json.loads(crops):
                crop_map[int(c["idx"])] = c
        except Exception:
            raise HTTPException(400, "crops JSON 파싱 실패")

    out_images = []
    for i, fn in enumerate(s["files"]):
        img = cv2.imread(os.path.join(s["dir"], fn), cv2.IMREAD_COLOR)
        if img is None:
            continue
        h, w = img.shape[:2]
        c = crop_map.get(i)
        if c:
            x, y = max(0, int(c["x"])), max(0, int(c["y"]))
            x2, y2 = min(w, x + int(c["w"])), min(h, y + int(c["h"]))
            if x2 > x and y2 > y:
                img = img[y:y2, x:x2]
        if paper:
            if paper not in PAPER_SIZES_MM:
                raise HTTPException(400, f"알 수 없는 용지: {paper}")
            img = fit_paper_canvas(img, paper, landscape) if paper_mode == "fit" \
                else fit_paper_crop(img, paper, landscape)
        out_images.append(img)

    if not out_images:
        raise HTTPException(400, "변환할 페이지가 없음")

    def encode(img, want):
        # want: 'png'(무손실) | 'jpg'(lossless면 q=100, 아니면 quality)
        if want == "png":
            ok, buf = cv2.imencode(".png", img, [cv2.IMWRITE_PNG_COMPRESSION, 6])
        else:
            q = 100 if lossless else quality
            ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])
        return buf.tobytes()

    if fmt == "pdf":
        # 무손실이면 각 페이지를 PNG(FlateDecode)로 PDF에 임베드 → 크롭 픽셀 그대로.
        # 작게 뽑고 싶으면 lossless=false (JPEG quality).
        page_enc = "png" if lossless else "jpg"
        doc = fitz.open()
        for img in out_images:
            hh, ww = img.shape[:2]
            pt_w, pt_h = ww * 72.0 / dpi, hh * 72.0 / dpi
            page = doc.new_page(width=pt_w, height=pt_h)
            page.insert_image(fitz.Rect(0, 0, pt_w, pt_h), stream=encode(img, page_enc))
        out_bytes = doc.tobytes(garbage=4, deflate=True)
        doc.close()
        return Response(out_bytes, media_type="application/pdf",
                        headers={"Content-Disposition": 'attachment; filename="webcrop.pdf"'})

    out_fmt = "jpg" if fmt == "jpg" else "png"  # PNG 출력은 언제나 무손실
    ext = ".jpg" if out_fmt == "jpg" else ".png"
    mt = "image/jpeg" if out_fmt == "jpg" else "image/png"
    if len(out_images) == 1:
        return Response(encode(out_images[0], out_fmt), media_type=mt,
                        headers={"Content-Disposition": f'attachment; filename="webcrop{ext}"'})

    mem = io.BytesIO()
    with zipfile.ZipFile(mem, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, img in enumerate(out_images, 1):
            zf.writestr(f"page_{i:03d}{ext}", encode(img, out_fmt))
    mem.seek(0)
    return StreamingResponse(mem, media_type="application/zip",
                             headers={"Content-Disposition": 'attachment; filename="webcrop.zip"'})
