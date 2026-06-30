#!/usr/bin/env python3
"""
just-this 전체 실행 — 허브 + 마운트된 모든 도구를 한 서버로 띄운다.

    pip install -r requirements.txt
    python run.py                 # http://localhost:8000

환경변수:
    HOST (기본 0.0.0.0)   PORT (기본 8000)   RELOAD=1 이면 코드 변경 자동 반영
"""

import os

import uvicorn

if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    reload = os.environ.get("RELOAD") == "1"
    print(f"just-this → http://localhost:{port}  (대시보드 + 모든 도구)")
    uvicorn.run("hub.app:app", host=host, port=port, reload=reload)
