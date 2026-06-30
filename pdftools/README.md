# PDF 합치기·편집·압축 (pdftools)

iLovePDF·Smallpdf 의 유료·광고 없이 로컬에서. PyMuPDF 기반, 모두 stateless.

## 기능 (탭)
- **합치기** — 여러 PDF·이미지를 순서대로 한 PDF로
- **페이지 편집** — 범위(`1-3,5,8-`)로 추출/삭제 + 회전(90/180/270)
- **압축** — 가볍게(무손실 정리) / 강하게(이미지 재압축, DPI 선택)
- **PDF→이미지** — 페이지별 PNG/JPG (여러 장 zip)
- **이미지→PDF** — 이미지 여러 장을 한 PDF로

## 실행
보통 just-this 허브에 묶여서 → `http://localhost:8000/pdftools/`.
단독: `pip install -r requirements.txt && uvicorn app:app`
