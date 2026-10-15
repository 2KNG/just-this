# 도구 통합 테스트

레포 루트에서 실행합니다. 별도 서버 실행은 필요 없습니다.

```bash
./venv/bin/python -m pytest -q tests
# 느린 테스트 확인
./venv/bin/python -m pytest -q tests --durations=10
```

- 모든 요청은 `TestClient(hub.app:app)`의 `/<slug>` 마운트를 사용합니다.
- Pillow 이미지·QR, PyMuPDF PDF, imageio-ffmpeg의 testsrc+sine 2초 영상을 실행 시 생성합니다.
- 이미지 형식·크기·메타데이터, PDF 페이지·순서·회전·용지, 영상 변환·편집·오디오를 검사합니다.
- ytdl은 임의 포트의 `127.0.0.1` HTTP 서버에서 HTML/video를 제공합니다. 실제 yt-dlp로 정보 조회,
  MP3/MP4 다운로드, 재생목록 폴링·ZIP, 한글 제목·다운로드 헤더를 검사하며 인터넷은 필요 없습니다.
- 오류·취소·동시 작업 제한은 통제된 추출기 실패/작업 상태로 재현합니다. 외부 TCP 연결은 차단합니다.
- 세션·작업·파일은 임시 경로로 격리하고, HTTP 서버와 백그라운드 작업은 종료 후 정리합니다.
- 앱 코드·HTML은 수정하지 않습니다. pytest 캐시는 `tests/` 아래에 저장합니다.
- 끝에 도구별 성공/실패 표를 출력합니다. 발견한 회귀는 `xfail`/skip으로 숨기지 않습니다.

의존성은 레포의 requirements와 `pytest`, `httpx`가 필요합니다. 영상은 ffprobe 없이 ffmpeg로
전체 스트림을 디코딩해 검증합니다. 각 테스트는 작은 입력과 짧은 폴링/명령 제한을 사용합니다.
devkit의 브라우저 JavaScript 동작은 이 HTTP 테스트의 검증 범위에 포함되지 않습니다.
