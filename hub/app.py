#!/usr/bin/env python3
"""
just-this 허브 — 레포의 모든 tool.json을 자동으로 읽어 한 페이지 대시보드로 보여준다.

도구 창고의 '현관'. 새 도구를 폴더 + tool.json 으로 추가하면 여기 자동으로 뜬다.
(루트 README의 정적 메뉴와 같은 데이터(tool.json)를 쓰되, 이쪽은 살아있는 웹 버전.)

실행:
    pip install -r requirements.txt
    uvicorn app:app                 # http://localhost:8000
    uvicorn app:app --host 0.0.0.0  # 같은 네트워크에 공유
"""

import os
import sys

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)  # 레포 루트 (hub의 부모)

# 도구 탐색 로직은 루트 index.py 와 단일 소스로 공유한다.
sys.path.insert(0, ROOT)
import index  # noqa: E402  (load_tools, CATEGORY_ORDER 재사용)

app = FastAPI(title="just-this 허브")
app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(HERE, "templates"))


def cat_key(c):
    order = index.CATEGORY_ORDER
    return (order.index(c) if c in order else len(order), c)


def discover():
    """tool.json 들을 읽어 (전체목록, 카테고리별 그룹) 을 돌려준다. 매 요청마다 새로 읽어 항상 최신."""
    tools = index.load_tools()  # ROOT 의 */tool.json 스캔
    groups = {}
    for t in tools:
        groups.setdefault(t.get("category", "기타"), []).append(t)
    ordered = [
        (cat, sorted(groups[cat], key=lambda t: t.get("slug", "")))
        for cat in sorted(groups, key=cat_key)
    ]
    return tools, ordered


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    tools, ordered = discover()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"groups": ordered, "total": len(tools)},
    )


@app.get("/api/tools")
def api_tools():
    """도구 메타데이터 JSON. 다른 데서 프로그램으로 긁어 쓸 때."""
    tools, _ = discover()
    return JSONResponse({"total": len(tools), "tools": tools})


@app.get("/healthz")
def healthz():
    return {"ok": True}
