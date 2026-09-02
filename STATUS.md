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

## 핸드오버 — 로컬에서 이어서 (2026-09-02, 원격 세션 → 로컬 teleport 완료)

### 어디까지 됐나
- PR #1 `claude/youtube-playlist-mp3-joqcpi`: **재생목록 → MP3** 탭(목록 훑기 → 체크한 곡만 백그라운드 작업 → 320k mp3 + 태그·앨범아트 → zip, 폰 대응).
  **로컬에서 실제 유튜브로 검증 완료**(아래).
- PR #2 `claude/youtube-playlist-mp3-handover-9w1w4k` (#1 위에 스택): **HTML-in-Canvas 진행 무대(`#pstage`)** 통합.
  회전 디스크 + 현재 곡 HTML 카드(순번·현재 곡 %·제목·업로더/길이)가 기울어져 슬라이드 인/아웃 + 전체 진행 링.
  done 은 초록 체크·zip 이름, error 는 주황 ✕, canceled 는 회색 ■, 실패 곡 카드는 주황 테두리.
  DOM(`#pcount #pbar #pcur #pfails …`)이 진실이고 캔버스는 장식 — 미지원 브라우저에선 `#pstage` hidden → 변화·에러·레이아웃 공간 0.
  코드는 `ytdl/static/index.html` 의 `PlStage` (CSS 16줄 + JS ~90줄), `renderJob()` 끝에서 `PlStage.update()` 한 줄.

### 실제 유튜브 검증 (로컬, 2026-09-02)
- `/api/playlist/info`: `youtube.com/playlist?list=`, `music.youtube.com/playlist?list=…&si=`, `watch?v=…&list=` 세 형태 모두 `youtube:tab` 추출기로 14곡 목록 ~3초.
- `start`(1곡 선택, 192k, 태그 on) → 9초 완료 → mp3 에 제목·아티스트 태그 + 앨범아트(png attached pic) 확인, `result` 200.
- 비공개 목록(로그인 필요)은 여전히 미지원.

### HTML-in-Canvas — 실증 사실 (크롬 141 / 151 / 152)
- 켜기: `--enable-blink-features=CanvasDrawElement`. 플래그 없으면 141·151·152 전부 API 없음(오리진 트라이얼 토큰 없인 안 보임).
- **API 이름이 바뀜**: 141 `ctx.drawElement(el,x,y)` → 151+ `ctx.drawElementImage(el,x,y)`. 151+ 엔 `canvas.requestPaint()`, `paint` 이벤트(자식이 바뀌면 자동 발생),
  `captureElementImage`, `getElementTransform` 도 생김. 코드는 두 이름을 다 받는다(`['drawElementImage','drawElement'].find(...)`).
- 151+: 갓 만들거나 갓 바꾼 요소를 같은 프레임에 그리면 `InvalidStateError: No cached paint record` → try/catch 로 삼키고 다음 프레임에 그려짐
  (끝 상태는 이중 rAF 로 한 장 더 그린다). 캔버스 **직계 자식만** 그릴 수 있음. 141 은 그리면 tainted, 151+ 는 안 됨(어차피 표시 전용).
- transform(회전·스케일)·globalAlpha 적용됨. 캔버스 자식의 CSS transition/animation 은 프레임에 반영 안 됨 → 애니메이션은 JS 에서.
- 캔버스 프리미티브는 CSS 변수를 못 읽어 같은 hex 를 하드코딩(#0f63ad #37a3df #1a9e5f #c2410c #d6e0ec #f4f7fb) — 팔레트 바꾸면 같이.

### 눈으로 보기 / 테스트 (Windows 기준)
```
venv\Scripts\Activate.ps1                                                    # 가상환경 이름은 venv
python run.py                                                                # 허브 http://localhost:8000 (8000 을 다른 앱이 쓰면 $env:PORT=8010)
python ytdl/devtest/make_fake_playlist.py --serve [--port 8812]              # 가짜 재생목록 (유튜브 없이 2초 완주)
python ytdl/devtest/ui_flow.py                                               # 폴백 경로(플래그 없음) 전체 흐름
python ytdl/devtest/ui_flow.py --flag --mobile --chromium "C:\Program Files\Google\Chrome\Application\chrome.exe"
    [--base http://localhost:8010/ytdl/ --playlist http://127.0.0.1:8812/list.html]   # 실제 크롬 152 로 390px
"C:\Program Files\Google\Chrome\Application\chrome.exe" --enable-blink-features=CanvasDrawElement http://localhost:8000/ytdl/   # 직접 보기
```
- `ui_flow.py` 는 무대도 검사한다: 지원이면 보임(높이>100, 캔버스 자식 2), 미지원이면 hidden·높이 0. 작업 완료 뒤 600ms 동안 rAF 호출 0. 새로고침 복원 경로도 같은 조건.
- `stage_edge.py` = 리뷰에서 실측된 경계 사례 회귀 테스트(플래그 켠 크롬 전용): ① 새 작업 시작 시 이전 링 리셋 ② 폴링 실패 후 rAF 정지
  ③ 다른 탭으로 가면 rAF 정지·돌아오면 재개 ④ 끝 상태에서 창 폭 바뀌면 다시 그림. 같은 `--base/--playlist/--chromium` 옵션.
- 4모드(플래그 유무 × 데스크톱/모바일; Playwright Chromium 151 + 실제 크롬 152) 콘솔·페이지 에러 0 통과, `stage_edge.py` 두 브라우저 통과.

### 남은 것 / 아이디어
- 플래그 없이 켜려면 오리진 트라이얼 토큰(`<meta http-equiv="origin-trial">`) — 개인 서버라 필요할 때 등록.
- 다른 컨셉(정보 밀도 타임라인 — 선택한 곡을 칩으로 배치해 50곡 한눈에)은 미착수. 지금 무대는 "플레이어 감성" 한 갈래.

### 원격 세션 메모
- 원격 세션 둘 다 PR 자동 체크인·이벤트 구독을 **꺼둠**. PR #1·#2 브랜치는 이제 로컬에서만 푸시함.
