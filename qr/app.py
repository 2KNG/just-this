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

HERE = os.path.dirname(os.path.abspath(__file__))
ECC = {"L": ERROR_CORRECT_L, "M": ERROR_CORRECT_M, "Q": ERROR_CORRECT_Q, "H": ERROR_CORRECT_H}

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
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color=hex_rgb(fg), back_color=hex_rgb(bg, (255, 255, 255))).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return Response(buf.getvalue(), media_type="image/png",
                    headers={"Content-Disposition": 'attachment; filename="qr.png"'})


@app.post("/api/read")
async def read(file: UploadFile = File(...)):
    data = await file.read()
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
    if not results:
        raise HTTPException(400, "QR 코드를 찾지 못함 (더 또렷한 이미지로 시도)")
    return JSONResponse({"results": results})
