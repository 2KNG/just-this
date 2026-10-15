#!/usr/bin/env python3
"""qr — QR 코드 생성/읽기. 생성은 qrcode, 읽기는 OpenCV QRCodeDetector."""
import io
import os

import cv2
import numpy as np
import qrcode
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from qrcode.constants import (ERROR_CORRECT_H, ERROR_CORRECT_L, ERROR_CORRECT_M,
                              ERROR_CORRECT_Q)
from starlette.concurrency import run_in_threadpool

HERE = os.path.dirname(os.path.abspath(__file__))
ECC = {"L": ERROR_CORRECT_L, "M": ERROR_CORRECT_M, "Q": ERROR_CORRECT_Q, "H": ERROR_CORRECT_H}
MAX_UPLOAD_MB = int(os.environ.get("JT_MAX_UPLOAD_MB", 300))

app = FastAPI(title="qr")


def hex_rgb(s, default=(0, 0, 0)):
    s = (s or "").lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    try:
        return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return default


@app.get("/", response_class=HTMLResponse)
def index():
    with open(os.path.join(HERE, "static", "index.html"), encoding="utf-8") as f:
        return f.read()


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.post("/api/generate")
async def generate(
    text: str = Form(...),
    ecc: str = Form("M"),
    box: int = Form(10),
    border: int = Form(4),
    fg: str = Form("#000000"),
    bg: str = Form("#ffffff"),
):
    if not text:
        raise HTTPException(400, "내용이 비어 있음")
    qr = qrcode.QRCode(error_correction=ECC.get(ecc, ERROR_CORRECT_M),
                       box_size=max(1, min(40, int(box))), border=max(0, min(16, int(border))))
    try:
        qr.add_data(text)
        qr.make(fit=True)
    except ValueError:   # DataOverflowError — 2953바이트 넘으면 500 대신 400
        raise HTTPException(400, "내용이 너무 김 (QR 용량 초과)")

    def _render():
        img = qr.make_image(fill_color=hex_rgb(fg), back_color=hex_rgb(bg, (255, 255, 255))).convert("RGB")
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return buf.getvalue()

    return Response(await run_in_threadpool(_render), media_type="image/png",
                    headers={"Content-Disposition": 'attachment; filename="qr.png"'})


def _decode(data):
    """OpenCV 디코드 (CPU 작업 → 스레드풀에서 호출)."""
    arr = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if arr is None:
        raise HTTPException(400, "이미지를 읽을 수 없음")
    det = cv2.QRCodeDetector()
    results = []
    ok, infos, pts, _ = det.detectAndDecodeMulti(arr)
    if ok:
        results = [t for t in infos if t]
    if not results:
        t, _, _ = det.detectAndDecode(arr)
        if t:
            results = [t]
    return results


@app.post("/api/read")
async def read(file: UploadFile = File(...)):
    limit = MAX_UPLOAD_MB * 1024 * 1024
    if file.size and file.size > limit:   # 메모리에 올리기 전에 거른다
        raise HTTPException(413, f"파일이 너무 큼 (최대 {MAX_UPLOAD_MB}MB)")
    data = await file.read()
    if len(data) > limit:
        raise HTTPException(413, f"파일이 너무 큼 (최대 {MAX_UPLOAD_MB}MB)")
    results = await run_in_threadpool(_decode, data)
    if not results:
        raise HTTPException(400, "QR 코드를 찾지 못함 (더 또렷한 이미지로 시도)")
    return JSONResponse({"results": results})
