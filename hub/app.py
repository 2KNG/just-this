#!/usr/bin/env python3
"""
just-this 허브 — 레포의 모든 도구를 한 서버에 모아 띄우는 셀프호스팅 대시보드.

핵심: 각 도구(FastAPI 웹앱)를 서브앱으로 '마운트'한다.
  → 루트에서 requirements 한 번 설치하고 이 허브 하나만 띄우면
    대시보드(/)와 모든 도구(/imgconv/, /webcrop/ …)가 같은 포트에서 다 돈다.

실행 (루트에서):
    pip install -r requirements.txt
    python run.py                       # http://localhost:8000
    # 또는: uvicorn hub.app:app --host 0.0.0.0 --port 8000
"""

import importlib
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

MOUNTED = {}  # slug -> True : 서브앱으로 마운트 성공한 도구
MOUNT_ERRORS = {}  # slug -> str : 마운트 실패 원인 (보통 의존성 미설치)


def mount_tools():
    """python 웹 도구들을 /{slug} 로 마운트. 코드가 없거나 import 실패하면 건너뛴다."""
    for t in index.load_tools():
        slug = t.get("slug")
        if not slug or slug == "hub":
            continue
        if t.get("lang") != "python" or t.get("type") != "web":
            continue
        if not os.path.isfile(os.path.join(ROOT, slug, "app.py")):
            continue  # 아직 코드 없음 (예: 메타데이터만 있는 도구)
        try:
            mod = importlib.import_module(f"{slug}.app")
            subapp = getattr(mod, "app", None)
            if subapp is None:
                continue
            app.mount(f"/{slug}", subapp)
            MOUNTED[slug] = True
            print(f"[hub] mounted /{slug}", file=sys.stderr)
        except Exception as e:  # 의존성 미설치 등 — 허브는 계속 뜬다
            MOUNT_ERRORS[slug] = f"{type(e).__name__}: {e}"
            print(f"[hub] /{slug} 마운트 실패 (pip install 확인): {e}", file=sys.stderr)


mount_tools()


def cat_key(c):
    order = index.CATEGORY_ORDER
    return (order.index(c) if c in order else len(order), c)


def discover():
    """tool.json 들을 읽어 (전체수, 카테고리별 그룹, 마운트수) 반환. 매 요청마다 새로 읽어 항상 최신."""
    # 허브 자신은 도구 목록에서 제외 (대시보드가 자기 자신을 나열할 필요 없음)
    tools = [t for t in index.load_tools() if t.get("slug") != "hub"]
    for t in tools:
        slug = t.get("slug", "")
        t["_mounted"] = slug in MOUNTED
        is_py_web = t.get("lang") == "python" and t.get("type") == "web"
        has_app = bool(slug) and os.path.isfile(os.path.join(ROOT, slug, "app.py"))
        # 코드는 있는데 마운트 안 됨 = 의존성 미설치 (pip install 다시 필요)
        t["_needs_deps"] = is_py_web and has_app and not t["_mounted"]
        if t["_mounted"]:
            t["_open"] = f"/{slug}/"
            t["_open_blank"] = False
        elif is_py_web and not has_app:
            # python 웹 도구인데 코드가 아직 없음 → 마운트 불가, 외부 링크도 무의미
            t["_open"] = None
            t["_open_blank"] = False
        elif t.get("entry") and str(t["entry"]).startswith("http"):
            t["_open"] = t["entry"]
            t["_open_blank"] = True
        else:
            t["_open"] = None
            t["_open_blank"] = False
    groups = {}
    for t in tools:
        groups.setdefault(t.get("category", "기타"), []).append(t)
    ordered = [
        (cat, sorted(groups[cat], key=lambda t: t.get("slug", "")))
        for cat in sorted(groups, key=cat_key)
    ]
    return len(tools), ordered, sum(1 for t in tools if t["_mounted"])


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    total, ordered, mounted = discover()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"groups": ordered, "total": total, "mounted": mounted},
    )


@app.get("/api/tools")
def api_tools():
    """도구 메타데이터 JSON."""
    total, ordered, mounted = discover()
    tools = [t for _cat, items in ordered for t in items]
    return JSONResponse({"total": total, "mounted": mounted, "tools": tools})


@app.get("/healthz")
def healthz():
    return {"ok": True, "mounted": sorted(MOUNTED), "mount_errors": MOUNT_ERRORS}
