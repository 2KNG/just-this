# STATUS — 현재 상태 메모

자동 갱신되는 README 메뉴 말고, 작업 맥락을 사람이 읽기 위한 메모.

## 구조 (단일 서버)
- 루트 `requirements.txt` 한 번 설치 → `python run.py` 한 번 실행 →
  허브 대시보드(`/`) + 모든 도구(`/{slug}/`)가 한 포트(기본 8000)에서 동작.
- 허브(`hub/app.py`)가 각 도구의 FastAPI `app` 을 `/{slug}` 서브앱으로 자동 마운트.
  의존성이 안 깔린 도구는 마운트 실패 → 대시보드에 "설치 필요" 표시, `/healthz` 의
  `mount_errors` 에 원인 노출. 도구 프론트 자산·API 는 **상대경로**(마운트 대응).
- 새 도구 추가: 폴더 + `tool.json` + `app.py` + (필요시) `static/index.html`,
  루트 `requirements.txt` 에 `-r <slug>/requirements.txt` 한 줄, 서버 재시작.
  메뉴 표 갱신은 `python index.py`. (상세 규칙은 CONVENTIONS.md / CLAUDE.md)

## 도구 (7개)
| slug | 카테고리 | 핵심 | 주요 의존성 |
|------|----------|------|-------------|
| imgconv | 문서 | 이미지 형식변환·자르기·리사이즈·EXIF제거 (HEIC 포함) | pillow, pillow-heif |
| webcrop | 문서 | PDF·문서 회전(실시간)·자르기(테두리 스냅)·용지 실치수·변환 | pymupdf, opencv-headless, numpy |
| pdftools | 문서 | PDF 합치기·페이지편집·압축·PDF↔이미지 | pymupdf, pillow |
| vidconv | 미디어 | 동영상 구간/영역 자르기·리사이즈·MP4/WEBM/GIF/MP3/PNG | imageio-ffmpeg |
| ytdl | 미디어 | 유튜브 영상/오디오·구간·자막 추출 | yt-dlp, imageio-ffmpeg |
| devkit | 개발 | JSON·Base64·URL·JWT·해시·타임스탬프·UUID (전부 브라우저) | (없음) |
| qr | 기타 | QR 생성·읽기 | qrcode, opencv-headless |

## 중요 메모
- **ffmpeg**: vidconv/ytdl 는 시스템 ffmpeg 우선, 없으면 pip `imageio-ffmpeg`
  정적 빌드(libx264/vp9/gif/aac/mp3 포함) 자동 사용. ytdl 은 그 바이너리를
  `ffmpeg` 이름으로 심볼릭/복사해 `ffmpeg_location` 으로 넘김.
- **ytdl 네트워크**: 실제 다운로드는 인터넷(유튜브 접속) 되는 환경에서만. 개발
  샌드박스는 프록시가 유튜브를 막아 라이브 다운로드는 미검증(옵션·에러처리는 검증).
- **webcrop 무손실/실치수**: 크롭은 브라우저(getCroppedCanvas)에서 보이는 그대로 →
  서버 조립. 용지 선택 시 PDF 페이지 = 그 용지 정확한 물리 치수(A4=210×297mm).
  용지 미선택이면 원본 스캔 치수(200DPI 기준) 보존.
- **프론트**: 모든 도구 밝은 파랑/흰색 톤 + 상단 네비게이션 바(다른 도구로 이동).
  Cropper.js 는 외부 CDN 대신 vendoring(`*/static/cropper.min.*`).

## 다음 후보 (미착수)
- 웹페이지→PDF/스크린샷 (Playwright 설치돼 있음; 서버에서 async playwright 필요)
- 이미지 배경 제거(rembg, 모델 다운로드 필요), OCR(tesseract)
- devkit 에 비밀번호 생성/정규식 테스터/색상 변환 탭 추가
- webcrop 페이지별 개별 회전, 멀티워커 대응(세션 공유 스토리지)
