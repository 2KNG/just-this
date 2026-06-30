#!/usr/bin/env python3
"""
imgconv — 이미지 형식변환 · 자르기 · 리사이즈 (원본 화질 보존).

온라인 변환 사이트(배치 제한·워터마크·광고) 없이 로컬에서.
- 형식변환: HEIC(아이폰)/PNG/JPG/WEBP/BMP/TIFF/GIF 입력 → PNG/JPG/WEBP 출력
- 자르기: 한 장일 때 마우스 드래그로 (Cropper.js, 원본 풀해상도에 적용 → 무손실)
- 리사이즈: 긴 변 / 가로 / 세로 / 퍼센트 기준
- 메타데이터(EXIF·GPS) 제거 옵션 (기본 ON, 프라이버시)
- 여러 장은 한 번에 변환 → zip

실행:
    pip install -r requirements.txt
    uvicorn app:app                 # http://localhost:8000
"""

import io
import json
import os
import re
import zipfile
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps

# 아이폰 HEIC 지원
try:
    import pillow_heif

    pillow_heif.register_heif_opener()
    HEIF_OK = True
except Exception:  # libheif 미설치 등
    HEIF_OK = False

HERE = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(title="imgconv")
app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")

# 출력 형식 → (PIL 포맷, 확장자, MIME)
OUT = {
    "png": ("PNG", "png", "image/png"),
    "jpg": ("JPEG", "jpg", "image/jpeg"),
    "webp": ("WEBP", "webp", "image/webp"),
}
# 원본 유지(keep) 시 PIL 포맷명 → 우리 출력키
KEEP_MAP = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}


def hex_to_rgb(s: str):
    s = (s or "#ffffff").lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    try:
        return tuple(int(s[i : i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return (255, 255, 255)


def process_one(data: bytes, opt: dict, crop=None):
    """이미지 한 장을 옵션대로 처리해 (bytes, 확장자) 반환."""
    im = Image.open(io.BytesIO(data))
    src_format = im.format  # 'JPEG', 'PNG', ...
    im = ImageOps.exif_transpose(im)  # EXIF 방향 적용 (눕는 사진 방지)

    # 자르기 — 자연 픽셀 좌표 [left, top, width, height]
    if crop:
        l, t, w, h = (int(round(v)) for v in crop)
        box = (max(0, l), max(0, t), min(im.width, l + w), min(im.height, t + h))
        if box[2] > box[0] and box[3] > box[1]:
            im = im.crop(box)

    # 리사이즈
    mode = opt.get("resize_mode", "none")
    val = int(opt.get("resize_value") or 0)
    if mode != "none" and val > 0:
        w, h = im.size
        if mode == "percent":
            nw, nh = max(1, w * val // 100), max(1, h * val // 100)
        elif mode == "width":
            nw, nh = val, max(1, round(h * val / w))
        elif mode == "height":
            nw, nh = max(1, round(w * val / h)), val
        elif mode == "longest":
            if w >= h:
                nw, nh = val, max(1, round(h * val / w))
            else:
                nw, nh = max(1, round(w * val / h)), val
        else:
            nw, nh = w, h
        if (nw, nh) != (w, h):
            im = im.resize((nw, nh), Image.LANCZOS)

    # 출력 형식 결정
    fmt = opt.get("fmt", "keep")
    if fmt == "keep":
        fmt = KEEP_MAP.get(src_format, "png")  # 모르는 형식이면 무손실 PNG로
    if fmt not in OUT:
        fmt = "png"
    pil_fmt, ext, _mime = OUT[fmt]

    strip = bool(opt.get("strip_meta", True))
    quality = int(opt.get("quality", 92))
    save_kwargs = {}

    if pil_fmt == "JPEG":
        if im.mode in ("RGBA", "LA", "P"):
            bg = Image.new("RGB", im.size, hex_to_rgb(opt.get("bg", "#ffffff")))
            rgba = im.convert("RGBA")
            bg.paste(rgba, mask=rgba.split()[-1])
            im = bg
        else:
            im = im.convert("RGB")
        save_kwargs.update(quality=quality, optimize=True, progressive=True)
    elif pil_fmt == "WEBP":
        if opt.get("webp_lossless"):
            save_kwargs.update(lossless=True, quality=100, method=6)
        else:
            save_kwargs.update(quality=quality, method=6)
    elif pil_fmt == "PNG":
        save_kwargs.update(optimize=True)

    # 메타데이터 유지 옵션 (기본은 제거)
    if not strip and pil_fmt in ("JPEG", "WEBP"):
        exif = im.info.get("exif")
        if exif:
            save_kwargs["exif"] = exif

    buf = io.BytesIO()
    im.save(buf, pil_fmt, **save_kwargs)
    return buf.getvalue(), ext


def safe_stem(name: str) -> str:
    stem = os.path.splitext(os.path.basename(name or "image"))[0]
    stem = re.sub(r"[\\/:*?\"<>|]+", "_", stem).strip() or "image"
    return stem


def content_disposition(filename: str) -> str:
    # 한글 파일명 대응 (RFC 5987)
    ascii_fallback = re.sub(r"[^\x20-\x7e]", "_", filename)
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(filename)}"


@app.get("/")
def home():
    return FileResponse(os.path.join(HERE, "static", "index.html"))


@app.get("/healthz")
def healthz():
    return {"ok": True, "heif": HEIF_OK}


@app.post("/api/convert")
async def convert(
    files: list[UploadFile] = File(...),
    options: str = Form("{}"),
):
    try:
        opt = json.loads(options or "{}")
    except json.JSONDecodeError:
        raise HTTPException(400, "옵션 JSON 파싱 실패")

    if not files:
        raise HTTPException(400, "파일이 없음")

    # 자르기는 한 장일 때만 (여러 장이면 어디를 자를지 모호)
    crop = opt.get("crop") if len(files) == 1 else None

    outputs = []  # (filename, bytes)
    skipped = []
    used_names = {}
    for f in files:
        data = await f.read()
        try:
            out, ext = process_one(data, opt, crop=crop)
        except Exception as e:  # 이미지가 아니거나 손상
            skipped.append(f"{f.filename}: {e}")
            continue
        name = f"{safe_stem(f.filename)}.{ext}"
        # zip 내 중복 이름 방지
        n = used_names.get(name, 0)
        used_names[name] = n + 1
        if n:
            base, dot, e = name.rpartition(".")
            name = f"{base}_{n}{dot}{e}"
        outputs.append((name, out))

    if not outputs:
        raise HTTPException(400, "변환할 수 있는 이미지가 없음. " + " / ".join(skipped))

    headers = {}
    if skipped:
        headers["X-Skipped"] = quote("; ".join(skipped))

    if len(outputs) == 1:
        name, out = outputs[0]
        _pil, ext, mime = OUT[name.rsplit(".", 1)[-1] if name.rsplit(".", 1)[-1] in OUT else "png"]
        headers["Content-Disposition"] = content_disposition(name)
        return Response(out, media_type=mime, headers=headers)

    # 여러 장 → zip
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, out in outputs:
            z.writestr(name, out)
    headers["Content-Disposition"] = content_disposition("imgconv.zip")
    return Response(zbuf.getvalue(), media_type="application/zip", headers=headers)
