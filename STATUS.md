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
| ytdl | 미디어 | 유튜브 영상/오디오·구간·자막 추출, 재생목록 일괄 MP3(zip) | yt-dlp, imageio-ffmpeg |
| devkit | 개발 | JSON·Base64·URL·JWT·해시·타임스탬프·UUID (전부 브라우저) | (없음) |
| qr | 기타 | QR 생성·읽기 | qrcode, opencv-headless |

## 중요 메모
- **ffmpeg**: vidconv/ytdl 는 시스템 ffmpeg 우선, 없으면 pip `imageio-ffmpeg`
  정적 빌드(libx264/vp9/gif/aac/mp3 포함) 자동 사용. ytdl 은 그 바이너리를
  `ffmpeg` 이름으로 심볼릭/복사해 `ffmpeg_location` 으로 넘김.
- **ytdl 네트워크**: 실제 다운로드는 인터넷(유튜브 접속) 되는 환경에서만. 개발
  샌드박스는 프록시가 유튜브를 막아 라이브 다운로드는 미검증(옵션·에러처리는 검증).
- **ytdl 재생목록**: `/api/playlist/*` — 목록 훑기(extract_flat) → 백그라운드 스레드 작업(job) →
  진행률 폴링 → zip(1곡이면 mp3). 작업 상태는 프로세스 메모리(`JOBS`)에만 있어 멀티워커·재시작 시
  유실. 곡별 실패는 건너뛰고 계속. yt-dlp 를 가짜로 바꿔 끼운 테스트로 zip·순번·중복이름·취소·전부실패 검증.
  실제 yt-dlp+정적 ffmpeg 로도 검증함: `<video poster>` 태그 3개짜리 로컬 HTML 을 localhost 로 서빙
  (yt-dlp generic 추출기가 재생목록으로 인식) → 320k mp3·한글 순번 zip·제목 태그·앨범아트 임베드 확인.
  유튜브 추출 자체만 샌드박스 프록시 정책(403)으로 미검증.
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

## 핸드오버 — 로컬 세션에서 이어서 (2026-09-02, 원격 세션 → 로컬)

### 어디까지 됐나
- 브랜치 `claude/youtube-playlist-mp3-joqcpi` → PR #1 (draft, main 대비 충돌 없음, CI 없음).
  ytdl 에 **재생목록 → MP3** 탭: 목록 훑기 → 체크한 곡만 백그라운드 작업 → 320k mp3(제목·아티스트·앨범아트 태그) → zip.
  폰 대응(직접 다운로드, 새로고침 후 이어받기)까지 포함. 상세는 PR 본문.
- **검증된 것**: 실제 yt-dlp + 정적 ffmpeg 파이프라인(로컬 가짜 재생목록으로), 390px 모바일 UI 흐름(Playwright).
- **미검증**: 유튜브 실접속 — 원격 샌드박스는 프록시가 `youtube.com` 을 막음(403). 로컬에서 실제 재생목록 하나로 한 번 돌려볼 것.
  비공개 재생목록(로그인 필요)은 미지원. `music.youtube.com/playlist?list=…` 는 `youtube:tab` 추출기로 처리됨(오프라인 확인).

### 로컬에서 돌려보기 (유튜브 없이도)
```bash
. venv/bin/activate
pip install playwright && playwright install chromium        # 테스트용, requirements 엔 안 넣음
python run.py                                                 # 터미널 1: 허브 http://localhost:8000
python ytdl/devtest/make_fake_playlist.py --serve             # 터미널 2: 가짜 재생목록 http://127.0.0.1:8811/list.html
python ytdl/devtest/ui_flow.py                                # 터미널 3: 폴백 경로(일반 브라우저) 전체 흐름
python ytdl/devtest/ui_flow.py --flag --mobile                # drawElement 켜고 390px
python ytdl/devtest/ui_flow.py --headed                       # 창 띄워서 눈으로
```
- `make_fake_playlist.py` = `<video poster>` 3개짜리 HTML → yt-dlp generic 추출기가 재생목록으로 인식. 한 곡 3초라 작업이 2초면 끝나 UI 반복에 좋다.
- `ui_flow.py` = 붙여넣기→목록→선택→진행→결과 다운로드→새로고침 이어받기. 콘솔/페이지 에러 있으면 exit 1. 스크린샷은 `ytdl/devtest/_shots/`.

### 다음 작업: HTML-in-Canvas 로 재생목록 진행 UI 꾸미기 (요청됨, 미착수)
크롬 오리진 트라이얼 "HTML in Canvas" — HTML 요소를 캔버스에 그리는 `drawElement`. 원격 세션에서 **Chromium 141 로 실증한 사실**:
- 켜기: `--enable-blink-features=CanvasDrawElement` (기본 크롬/사파리/폰 브라우저엔 **없음** — 오리진 트라이얼 토큰 없이는 안 보임).
  감지: `'drawElement' in CanvasRenderingContext2D.prototype`.
- 마크업 `<canvas layoutsubtree>…자식 요소…</canvas>`: 자식은 레이아웃은 되지만 DOM 이 그리진 않음. 지원 안 하는 브라우저에서도 캔버스 자식은 원래 안 보임 → **폴백은 기존 DOM UI 그대로**여야 함(캔버스 자식으로 폴백 X).
- 그리기: `ctx.drawElement(el, x, y[, w, h])` — 현재 transform(회전·스케일) 적용됨. 그라데이션·한글·이모지 카드 회전 렌더 확인.
- **제약**: drawElement 후 캔버스가 tainted → `toDataURL`/`getImageData` 불가(PNG 내보내기 용도 불가, 표시 전용).
  이 빌드엔 `requestPaint` 류 없음 → rAF 로 직접 재그리기(작업 중일 때만, `document.hidden` 이면 멈춤). HiDPI 는 `devicePixelRatio` 로.
- 설계 원칙: 점진적 향상. DOM(`#pjob` 진행바·현재곡·버튼)이 진실이고 캔버스는 장식. 미지원 시 변화·에러 0. 기존 셀렉터(`#pcount #pbar #pcur #presult …`) 유지.
- 아이디어(원격 세션에서 설계 중이던 세 갈래): ① 플레이어 감성 — 회전 디스크 + 현재 곡 HTML 카드가 기울어져 들어오고 진행 링,
  ② 정보 밀도 — 선택한 곡들을 HTML 칩으로 캔버스 타임라인에 배치해 대기→받는 중→완료/실패 애니메이션(50곡도 한눈에),
  ③ 최소 — 현재 곡 카드 슬라이드 + 진행 아크만(120줄 이내). 폰에서 쓰는 도구라 ③→① 순으로 무난.
- 눈으로 보려면: `chrome --enable-blink-features=CanvasDrawElement` 로 크롬 띄우거나 `ui_flow.py --flag --headed`.

### 원격 세션 메모
- 원격 세션이 PR #1 을 1시간마다 체크인 중(CI 없고 리뷰 없으면 아무것도 안 함). 로컬에서 같은 브랜치에 푸시해도 됨.
