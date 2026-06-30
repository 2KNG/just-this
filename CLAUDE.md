# CLAUDE.md — 이 레포에서 작업할 때 규칙

## 가상환경 (중요)
- 가상환경 디렉터리 이름은 **항상 `venv`** (점 없이). `.venv` 쓰지 말 것.
  - 생성: `python -m venv venv`
  - 활성화: Linux/mac `. venv/bin/activate` · Windows `venv\Scripts\Activate.ps1`

## 실행 구조 — 단일 서버
- 루트 `requirements.txt` **한 번 설치** → `python run.py` **한 번 실행**으로
  허브 대시보드 + 모든 도구가 한 포트(기본 8000)에서 다 돈다.
- 허브(`hub/app.py`)가 각 도구를 `/{slug}` 로 서브앱 마운트. 도구 페이지는
  마운트 밑에서 동작해야 하므로 **프론트 자산·API 경로는 상대경로**로 작성.
- 새 도구 추가: 폴더 + `tool.json` + `app.py`(FastAPI `app`) 만들고,
  루트 `requirements.txt`에 `-r <slug>/requirements.txt` 한 줄 추가 → 재시작.
  메뉴 표 갱신은 `python index.py`. (도구 추가 상세 규칙은 CONVENTIONS.md)

## 기타
- 비밀키·토큰 커밋 금지. 도구별 의존성은 각 폴더 `requirements.txt`에 격리.
