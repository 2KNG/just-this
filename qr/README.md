# QR 코드 생성·읽기 (qr)

텍스트·URL을 QR로 만들고, 거꾸로 QR 이미지에서 내용을 읽어낸다. 추적·만료·광고 거는 온라인 생성기 대신 로컬에서.

## 기능
- **생성** — 오류보정(L/M/Q/H)·크기·여백·전경/배경색 선택, PNG 다운로드
- **읽기** — QR 이미지 업로드 → 내용 추출 (여러 개도)

## 실행
허브에 묶여서 → `http://localhost:8000/qr/`. 단독: `pip install -r requirements.txt && uvicorn app:app`
