# just-this

> 여기저기 검색하고, 광고 보고, 결제하고, 시간 버리는 짓 그만.
> 딱 필요한 도구만 직접 만들어서 차곡차곡 박아두는 개인 창고.

매번 웹에서 찾아 헤매던 유틸들을 한 곳에. 새 도구 추가는
[CONVENTIONS.md](./CONVENTIONS.md) 규칙대로 폴더 + `tool.json` 만들고
`python index.py` 한 번이면 아래 메뉴가 자동 갱신됨.

## 메뉴

<!-- TOOLS:START -->

총 **2개** 도구

### 문서

| 도구 | 설명 | 실행 | 대체 |
|------|------|------|------|
| [문서 보정·변환](./webcrop/) | 스캔 PDF/이미지를 자동 기울기 보정(deskew)하고, 마우스로 영역을 잘라 A4·Letter·명함 등 표준 용지 규격에 맞춘 뒤 PDF/PNG/JPG로 변환하는 웹앱. | `pip install -r requirements.txt && uvicorn app:app --reload` | 온라인 PDF 편집/변환 결제 사이트 (iLovePDF, Smallpdf 등 유료 기능) |

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
