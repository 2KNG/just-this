# just-this

> 여기저기 검색하고, 광고 보고, 결제하고, 시간 버리는 짓 그만.
> 딱 필요한 도구만 직접 만들어서 차곡차곡 박아두는 개인 창고.

매번 웹에서 찾아 헤매던 유틸들을 한 곳에.

## 한 번에 설치·실행

도구마다 따로 설치·실행할 필요 없음. 서버 PC에서 **한 번 설치, 한 번 실행**하면
대시보드와 모든 도구가 같은 서버(한 포트)에서 다 돌아간다.

```bash
git clone https://github.com/2KNG/just-this.git
cd just-this
python -m venv venv                            # 가상환경 이름은 항상 venv (점 없이)
. venv/bin/activate                            # Windows: venv\Scripts\Activate.ps1
pip install -r requirements.txt                # 모든 도구 의존성 한 방에
python run.py                                   # http://localhost:8000
```

- 대시보드: <http://localhost:8000/>
- 각 도구: <http://localhost:8000/imgconv/> 처럼 `/{도구}/` 로 바로 접속 (허브가 서브앱으로 마운트)
- 같은 네트워크의 다른 기기에서 쓰려면 `run.py` 가 이미 `0.0.0.0` 바인딩. 포트는 `PORT=9000 python run.py`.

> 새 도구를 추가하면(폴더 + `tool.json` + `app.py`) `pip install -r requirements.txt` 다시 돌리고
> 서버 재시작하면 대시보드에 자동 등록·마운트된다. 메뉴 표 갱신은 `python index.py`.

## 메뉴

<!-- TOOLS:START -->

총 **3개** 도구

### 문서

| 도구 | 설명 | 실행 | 대체 |
|------|------|------|------|
| [이미지 변환·자르기](./imgconv/) | HEIC(아이폰)·PNG·JPG·WEBP 등 이미지를 무손실 우선으로 형식변환하고, 마우스로 자르고, 리사이즈하고, 메타데이터(EXIF·GPS)까지 제거하는 웹앱. 여러 장은 한 번에 zip. | `uvicorn app:app` | 온라인 이미지 변환·자르기 사이트 (배치 제한·워터마크·광고) |
| [PDF·문서 자르기·회전·변환](./webcrop/) | PDF·스캔 이미지를 회전·자동 기울기 보정(deskew)하고, 마우스로 영역을 잘라 A4·Letter·명함 등 표준 용지 규격에 맞춘 뒤 PDF/PNG/JPG로 변환하는 웹앱. | `uvicorn app:app` | 온라인 PDF 편집/변환 결제 사이트 (iLovePDF, Smallpdf 등 유료 기능) |

### 기타

| 도구 | 설명 | 실행 | 대체 |
|------|------|------|------|
| [just-this 허브](./hub/) | 레포의 모든 tool.json을 자동으로 읽어 카테고리·검색·태그로 보여주는 셀프호스팅 대시보드. 도구 창고의 현관. | `pip install -r requirements.txt && uvicorn app:app` | 도구마다 주소·실행법을 따로 북마크/메모로 관리하던 짓 |

<!-- TOOLS:END -->

## 새 도구 추가
[CONVENTIONS.md](./CONVENTIONS.md) 참고. 요약:
1. 폴더 만들고 코드 + `tool.json` 넣기
2. `python index.py` 실행
3. 커밋
