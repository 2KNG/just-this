#!/usr/bin/env python3
"""
just-this 전체 실행 — 허브 + 마운트된 모든 도구를 한 서버로 띄운다.

    pip install -r requirements.txt
    python run.py                 # http://localhost:8000

환경변수:
    HOST (기본 0.0.0.0)   PORT (기본 8000)   RELOAD=1 이면 코드 변경 자동 반영
    JT_PIN (또는 루트 .jt_pin 파일) 설정 시 전체 도구 PIN 잠금 활성화
"""

import os

import uvicorn

if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    reload = os.environ.get("RELOAD") == "1"
    pin_on = bool(os.environ.get("JT_PIN", "").strip() or os.path.isfile(".jt_pin"))
    pin_msg = "🔒 PIN 잠금 활성" if pin_on else "PIN 잠금 꺼짐 (JT_PIN=1234 또는 .jt_pin 파일로 활성화)"
    print(f"just-this → http://localhost:{port}  (대시보드 + 모든 도구 · {pin_msg})")
    uvicorn.run("hub.app:app", host=host, port=port, reload=reload)
