# 동영상 자르기·변환 (vidconv)

동영상을 **구간 자르기(trim)**·**영역 자르기(crop)**·리사이즈하고 MP4/WEBM/GIF/MP3/PNG 로 바꾸는 웹앱. ffmpeg 기반.

## 기능
- **구간 자르기** — 영상 플레이어로 보면서 시작/끝 지정 (현재 위치로 바로 설정)
- **영역 자르기** — 대표 프레임 위에서 드래그(Cropper.js)
- **리사이즈** — 가로 기준 (1280/854/640/320…)
- **출력** — MP4(H.264) · WEBM(VP9) · GIF(팔레트 최적화) · MP3(오디오만) · PNG(프레임)
- 소리 제거, 화질(높음/보통/작게)

## 실행
보통 just-this 허브에 묶여서 한 번에 돈다 → `http://localhost:8000/vidconv/`.
단독: `pip install -r requirements.txt && uvicorn app:app`

## 메모
- ffmpeg 는 시스템에 있으면 그걸, 없으면 pip `imageio-ffmpeg` 정적 빌드를 자동 사용.
- 업로드 500MB 제한, 세션 30분 자동 정리.
