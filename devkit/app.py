#!/usr/bin/env python3
"""devkit — 개발 유틸 모음. 모든 처리는 브라우저(클라이언트)에서. 서버는 페이지만 서빙."""
import os
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

HERE = os.path.dirname(os.path.abspath(__file__))
app = FastAPI(title="devkit")


@app.get("/", response_class=HTMLResponse)
def index():
    with open(os.path.join(HERE, "static", "index.html"), encoding="utf-8") as f:
        return f.read()


@app.get("/healthz")
def healthz():
    return {"ok": True}
