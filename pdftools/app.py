#!/usr/bin/env python3
"""
pdftools — PDF 합치기 · 페이지 편집(추출·삭제·회전) · 압축 · PDF↔이미지.

iLovePDF/Smallpdf 의 유료·광고 없이 로컬에서. PyMuPDF(fitz) + Pillow.
모든 처리는 stateless: 파일 받아서 처리해 바로 내려준다.
"""

import io
import os
import re
import zipfile

import fitz  # PyMuPDF
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, Response

HERE = os.path.dirname(os.path.abspath(__file__))
MAX_MB = 100

app = FastAPI(title="pdftools")
from fastapi.staticfiles import StaticFiles  # noqa: E402
app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")


def _read(file: UploadFile) -> bytes:
    return file.file.read()


def _is_pdf(name, data):
    return (name or "").lower().endswith(".pdf") or data[:5] == b"%PDF-"


def open_as_pdf(name, data):
    """PDF면 그대로, 이미지면 1페이지 PDF로 변환해 fitz.Document 반환."""
    if _is_pdf(name, data):
        return fitz.open(stream=data, filetype="pdf")
    # 이미지 → PDF
    img = fitz.open(stream=data)  # fitz 가 이미지도 염
    pdfbytes = img.convert_to_pdf()
    img.close()
    return fitz.open(stream=pdfbytes, filetype="pdf")


def parse_ranges(spec, n):
    """'1-3,5,7-' → 0-based 인덱스 리스트(1-based 입력). 빈값이면 전체."""
    spec = (spec or "").strip()
    if not spec:
        return list(range(n))
    out = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^(\d+)?\s*-\s*(\d+)?$", part)
        if m:
            a = int(m.group(1)) if m.group(1) else 1
            b = int(m.group(2)) if m.group(2) else n
            for i in range(a, b + 1):
                if 1 <= i <= n:
                    out.append(i - 1)
        elif part.isdigit():
            i = int(part)
            if 1 <= i <= n:
                out.append(i - 1)
        else:
            raise HTTPException(400, f"페이지 범위 형식 오류: {part}")
    return out


def pdf_response(doc, filename, garbage=4):
    data = doc.tobytes(garbage=garbage, deflate=True)
    doc.close()
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/", response_class=HTMLResponse)
def index():
    with open(os.path.join(HERE, "static", "index.html"), encoding="utf-8") as f:
        return f.read()


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.post("/api/merge")
async def merge(files: list[UploadFile] = File(...)):
    """여러 PDF/이미지를 순서대로 한 PDF로 합치기."""
    if len(files) < 1:
        raise HTTPException(400, "파일이 없음")
    out = fitz.open()
    for f in files:
        data = _read(f)
        if len(data) > MAX_MB * 1024 * 1024:
            raise HTTPException(413, "파일이 너무 큼")
        src = open_as_pdf(f.filename, data)
        out.insert_pdf(src)
        src.close()
    if out.page_count == 0:
        raise HTTPException(400, "합칠 페이지가 없음")
    return pdf_response(out, "merged.pdf")


@app.post("/api/pages")
async def pages(file: UploadFile = File(...), select: str = Form(""), rotate: int = Form(0)):
    """페이지 추출/삭제(select 범위만 남김) + 회전."""
    data = _read(file)
    doc = fitz.open(stream=data, filetype="pdf")
    keep = parse_ranges(select, doc.page_count)
    if not keep:
        raise HTTPException(400, "남길 페이지가 없음")
    doc.select(keep)
    r = int(rotate) % 360
    if r:
        for p in doc:
            p.set_rotation((p.rotation + r) % 360)
    return pdf_response(doc, "pages.pdf")


@app.post("/api/compress")
async def compress(file: UploadFile = File(...), level: str = Form("light"), dpi: int = Form(120)):
    """light=무손실 정리 / strong=이미지 재렌더(JPEG)로 강하게."""
    data = _read(file)
    doc = fitz.open(stream=data, filetype="pdf")
    if level == "strong":
        out = fitz.open()
        d = max(60, min(300, int(dpi)))
        for page in doc:
            pix = page.get_pixmap(matrix=fitz.Matrix(d / 72, d / 72), alpha=False)
            jb = io.BytesIO()
            from PIL import Image
            Image.frombytes("RGB", (pix.width, pix.height), pix.samples).save(jb, "JPEG", quality=75)
            r = page.rect
            np_ = out.new_page(width=r.width, height=r.height)
            np_.insert_image(np_.rect, stream=jb.getvalue())
        doc.close()
        return pdf_response(out, "compressed.pdf")
    return pdf_response(doc, "compressed.pdf", garbage=4)


@app.post("/api/to_images")
async def to_images(file: UploadFile = File(...), fmt: str = Form("png"), dpi: int = Form(150)):
    data = _read(file)
    doc = fitz.open(stream=data, filetype="pdf")
    d = max(36, min(600, int(dpi)))
    ext = "jpg" if fmt == "jpg" else "png"
    mt = "image/jpeg" if ext == "jpg" else "image/png"
    from PIL import Image
    imgs = []
    for page in doc:
        pix = page.get_pixmap(matrix=fitz.Matrix(d / 72, d / 72), alpha=False)
        im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        b = io.BytesIO()
        if ext == "jpg":
            im.save(b, "JPEG", quality=92)
        else:
            im.save(b, "PNG", optimize=True)
        imgs.append(b.getvalue())
    doc.close()
    if not imgs:
        raise HTTPException(400, "페이지가 없음")
    if len(imgs) == 1:
        return Response(imgs[0], media_type=mt,
                        headers={"Content-Disposition": f'attachment; filename="page.{ext}"'})
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as z:
        for i, b in enumerate(imgs, 1):
            z.writestr(f"page_{i:03d}.{ext}", b)
    return Response(zbuf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="pages.zip"'})


@app.post("/api/from_images")
async def from_images(files: list[UploadFile] = File(...)):
    """이미지 여러 장 → 1 PDF (각 이미지가 한 페이지)."""
    out = fitz.open()
    for f in files:
        data = _read(f)
        img = fitz.open(stream=data)
        pdfbytes = img.convert_to_pdf()
        img.close()
        out.insert_pdf(fitz.open(stream=pdfbytes, filetype="pdf"))
    if out.page_count == 0:
        raise HTTPException(400, "이미지가 없음")
    return pdf_response(out, "images.pdf")
