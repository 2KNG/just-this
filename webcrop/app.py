#!/usr/bin/env python3
"""
webcrop — PDF·이미지를 자르고(crop) 회전(rotate)하고 변환(convert)하는 웹앱.

흐름 (회전은 브라우저에서 실시간):
  1) 업로드: PDF/PNG/JPG → 서버가 페이지를 렌더(+선택적 deskew) → 미리보기 PNG.
             각 페이지의 '내용 경계(contour)'도 같이 계산해 스냅용으로 내려줌.
  2) 편집  : 브라우저 Cropper.js 에서 회전 슬라이더(-180~180)로 실시간 회전,
             드래그로 crop. '테두리 스냅' 켜면 내용 경계에 딱 맞춤.
  3) 변환  : 브라우저가 회전+크롭 결과(getCroppedCanvas)를 PNG로 만들어 보내고,
             서버는 용지 맞춤 + PDF/PNG/JPG 로 조립. 기본 무손실.

단일 프로세스로 실행. 세션(미리보기)은 임시폴더, 30분 TTL.
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
RENDER_DPI = 200  # 미리보기=작업 해상도. Cropper 회전은 CSS 변환이라 이 해상도여도 부드럽다.
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
            if pix.n == 1:
                arr = cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
            else:
                arr = cv2.cvtColor(arr[:, :, :3], cv2.COLOR_RGB2BGR)
            out.append(np.ascontiguousarray(arr))
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


def content_bbox(img):
    """문서 내용(글자·도형)의 바깥 경계 박스 [x, y, w, h]. 스냅 자르기용. 없으면 전체."""
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE,
                          cv2.getStructuringElement(cv2.MORPH_RECT, (25, 25)))
    cnts, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_area = w * h * 0.0008
    boxes = [cv2.boundingRect(c) for c in cnts if cv2.contourArea(c) > min_area]
    if not boxes:
        return [0, 0, w, h]
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[0] + b[2] for b in boxes)
    y1 = max(b[1] + b[3] for b in boxes)
    pad = 4
    x0, y0 = max(0, x0 - pad), max(0, y0 - pad)
    x1, y1 = min(w, x1 + pad), min(h, y1 + pad)
    return [int(x0), int(y0), int(x1 - x0), int(y1 - y0)]


def paper_ratio(paper, landscape):
    mm_w, mm_h = PAPER_SIZES_MM[paper]
    if landscape:
        mm_w, mm_h = mm_h, mm_w
    return mm_w / mm_h


def paper_points(paper, landscape):
    """용지 실제 물리 치수 → PDF 포인트(1pt=1/72인치). A4 → 정확히 210×297mm."""
    mm_w, mm_h = PAPER_SIZES_MM[paper]
    if landscape:
        mm_w, mm_h = mm_h, mm_w
    return mm_w / 25.4 * 72.0, mm_h / 25.4 * 72.0


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


# ---------------- 라우트 ----------------
@app.get("/", response_class=HTMLResponse)
def index():
    with open(os.path.join(HERE, "static", "index.html"), encoding="utf-8") as f:
        return f.read()


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.post("/api/upload")
async def upload(file: UploadFile = File(...), auto_deskew: bool = Form(False)):
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
        if auto_deskew:
            ang = detect_skew_angle(img)
            if abs(ang) > 0.05:
                img = rotate_image(img, ang)
        fn = f"page_{i:03d}.png"
        cv2.imwrite(os.path.join(sdir, fn), img)
        h, w = img.shape[:2]
        files.append(fn)
        pages.append({
            "idx": i, "w": int(w), "h": int(h),
            "url": f"api/preview/{token}/{i}",   # 상대경로 — /webcrop 마운트 대응
            "snap": content_bbox(img),
        })

    SESSIONS[token] = {"dir": sdir, "files": files, "ts": time.time()}
    return {"token": token, "pages": pages}


@app.get("/api/preview/{token}/{idx}")
def preview(token: str, idx: int):
    s = SESSIONS.get(token)
    if not s or idx < 0 or idx >= len(s["files"]):
        raise HTTPException(404, "페이지 없음 (세션 만료일 수 있음)")
    return FileResponse(os.path.join(s["dir"], s["files"][idx]), media_type="image/png")


@app.post("/api/assemble")
async def assemble(
    files: list[UploadFile] = File(...),   # 브라우저가 만든 페이지별 PNG (회전+크롭 완료)
    fmt: str = Form("pdf"),                # pdf | png | jpg
    paper: str = Form(""),                # "" 또는 a4/letter/...
    paper_mode: str = Form("crop"),       # crop | fit
    landscape: bool = Form(False),
    lossless: bool = Form(True),
    quality: int = Form(95),
):
    pages = []
    for f in files:
        raw = np.frombuffer(await f.read(), np.uint8)
        img = cv2.imdecode(raw, cv2.IMREAD_COLOR)
        if img is None:
            continue
        if paper:
            if paper not in PAPER_SIZES_MM:
                raise HTTPException(400, f"알 수 없는 용지: {paper}")
            img = fit_paper_canvas(img, paper, landscape) if paper_mode == "fit" \
                else fit_paper_crop(img, paper, landscape)
        pages.append(img)

    if not pages:
        raise HTTPException(400, "변환할 페이지가 없음")

    def encode(img, want):
        if want == "png":
            return cv2.imencode(".png", img, [cv2.IMWRITE_PNG_COMPRESSION, 6])[1].tobytes()
        q = 100 if lossless else quality
        return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])[1].tobytes()

    if fmt == "pdf":
        page_enc = "png" if lossless else "jpg"
        doc = fitz.open()
        for img in pages:
            hh, ww = img.shape[:2]
            if paper:
                # 용지 선택 시 PDF 페이지를 그 용지의 정확한 물리 치수로 (A4=210×297mm)
                pt_w, pt_h = paper_points(paper, landscape)
            else:
                # 용지 없으면 원본 스캔의 물리 치수 보존 (RENDER_DPI 기준)
                pt_w, pt_h = ww * 72.0 / RENDER_DPI, hh * 72.0 / RENDER_DPI
            pg = doc.new_page(width=pt_w, height=pt_h)
            pg.insert_image(fitz.Rect(0, 0, pt_w, pt_h), stream=encode(img, page_enc))
        out = doc.tobytes(garbage=4, deflate=True)
        doc.close()
        return Response(out, media_type="application/pdf",
                        headers={"Content-Disposition": 'attachment; filename="webcrop.pdf"'})

    out_fmt = "jpg" if fmt == "jpg" else "png"
    ext = ".jpg" if out_fmt == "jpg" else ".png"
    mt = "image/jpeg" if out_fmt == "jpg" else "image/png"
    if len(pages) == 1:
        return Response(encode(pages[0], out_fmt), media_type=mt,
                        headers={"Content-Disposition": f'attachment; filename="webcrop{ext}"'})
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, img in enumerate(pages, 1):
            zf.writestr(f"page_{i:03d}{ext}", encode(img, out_fmt))
    mem.seek(0)
    return StreamingResponse(mem, media_type="application/zip",
                             headers={"Content-Disposition": 'attachment; filename="webcrop.zip"'})
