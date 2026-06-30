# CONVENTIONS

`just-this`에 도구를 차곡차곡 쌓기 위한 규칙. 도구가 늘어도 루트 메뉴가 안 어지럽게.

## 핵심 원칙
> 검색하고 광고 보고 결제하느라 시간 버리는 짓을 안 하려고, 필요한 도구를 직접 만들어 여기 박아둔다.

도구 하나 = 폴더 하나. 폴더 안에 `tool.json` 하나만 규칙대로 넣으면, 루트 `README.md`의 메뉴가 자동으로 갱신된다.

## 새 도구 추가하는 법

1. 루트에 도구 폴더를 만든다. 폴더명 = slug (소문자, 하이픈). 예: `ytdl`, `webcrop`
2. 폴더 안에 **`tool.json`** 을 넣는다 (아래 스키마)
3. `README.md`(도구 설명), 실제 코드, 필요하면 `requirements.txt`를 넣는다
4. 루트에서 `python index.py` 실행 → 루트 README 메뉴 자동 갱신
5. 커밋

## tool.json 스키마

```json
{
  "name": "사람이 읽는 이름",
  "slug": "폴더명과 동일",
  "category": "문서",
  "description": "한 줄 설명. 뭘 하는 도구인지.",
  "lang": "python",
  "type": "web",
  "run": "실행 명령 (예: uvicorn app:app --reload)",
  "entry": "http://localhost:8000  (웹이면 접속 주소, CLI면 생략 가능)",
  "tags": ["pdf", "image"],
  "replaces": "이게 대체하는 유료/광고 서비스 (선택)"
}
```

| 필드 | 필수 | 설명 |
|------|------|------|
| `name` | ✅ | 메뉴에 표시될 이름 |
| `slug` | ✅ | 폴더명과 동일하게 |
| `category` | ✅ | 메뉴 분류. 기존 카테고리 재사용 우선 (아래 목록) |
| `description` | ✅ | 한 줄 설명 |
| `lang` | ✅ | python / node / bash / ... |
| `type` |  | web / cli / script |
| `run` |  | 실행 명령 |
| `entry` |  | 웹 접속 주소 |
| `tags` |  | 검색용 태그 배열 |
| `replaces` |  | 대체하는 유료 서비스 (자급자족 컨셉 기록용) |

## 카테고리 (기존 것 재사용 우선)
- `문서` — PDF, 이미지, 변환, OCR 류
- `미디어` — 영상/음악 다운로드·변환 류
- `웹` — 스크래핑, 다운로더, 자동화
- `개발` — 코드 유틸, 포맷터, 변환기
- `기타`

새 카테고리가 정말 필요할 때만 추가하고, 추가하면 이 목록도 갱신.

## 폴더 구조 예시
```
just-this/
├── README.md         ← 자동 생성 (직접 수정 X, 마커 사이만 갱신됨)
├── CONVENTIONS.md     ← 이 파일
├── index.py           ← 메뉴 생성기
├── webcrop/
│   ├── tool.json
│   ├── README.md
│   ├── requirements.txt
│   ├── app.py
│   └── static/
└── ytdl/
    ├── tool.json
    └── ...
```

## 규칙 몇 가지
- 루트 `README.md`의 `<!-- TOOLS:START -->` ~ `<!-- TOOLS:END -->` 사이는 **손대지 말 것**. `index.py`가 덮어씀.
- 도구별 의존성은 도구 폴더 안에서 격리 (각자 `requirements.txt`).
- 비밀키·토큰은 절대 커밋 금지. 필요하면 `.env`(gitignore됨) + `.env.example`.
