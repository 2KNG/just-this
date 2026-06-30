#!/usr/bin/env python3
"""
index.py — 루트 README.md의 도구 메뉴를 자동 생성.

각 하위 폴더의 tool.json을 읽어서 카테고리별 테이블로 묶고,
README.md 의 <!-- TOOLS:START --> ~ <!-- TOOLS:END --> 사이를 갈아끼운다.

사용:
    python index.py            # README 갱신
    python index.py --check    # 갱신 필요 여부만 확인 (CI용, 변경 필요시 exit 1)
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
README = os.path.join(HERE, "README.md")
START = "<!-- TOOLS:START -->"
END = "<!-- TOOLS:END -->"

# 카테고리 표시 순서 (없는 카테고리는 뒤에 알파벳순)
CATEGORY_ORDER = ["문서", "미디어", "웹", "개발", "기타"]


def load_tools():
    tools = []
    for entry in sorted(os.listdir(HERE)):
        path = os.path.join(HERE, entry)
        tj = os.path.join(path, "tool.json")
        if os.path.isdir(path) and os.path.isfile(tj):
            try:
                with open(tj, encoding="utf-8") as f:
                    data = json.load(f)
            except json.JSONDecodeError as e:
                print(f"[경고] {entry}/tool.json 파싱 실패: {e}", file=sys.stderr)
                continue
            data.setdefault("slug", entry)
            data.setdefault("category", "기타")
            data.setdefault("name", entry)
            data.setdefault("description", "")
            tools.append(data)
    return tools


def build_menu(tools):
    if not tools:
        return "_아직 등록된 도구가 없음. CONVENTIONS.md 참고해서 추가._"

    # 카테고리별 그룹
    groups = {}
    for t in tools:
        groups.setdefault(t["category"], []).append(t)

    def cat_key(c):
        return (CATEGORY_ORDER.index(c) if c in CATEGORY_ORDER
                else len(CATEGORY_ORDER), c)

    lines = []
    total = len(tools)
    lines.append(f"총 **{total}개** 도구\n")

    for cat in sorted(groups, key=cat_key):
        items = sorted(groups[cat], key=lambda t: t["slug"])
        lines.append(f"### {cat}\n")
        lines.append("| 도구 | 설명 | 실행 | 대체 |")
        lines.append("|------|------|------|------|")
        for t in items:
            name = f"[{t['name']}](./{t['slug']}/)"
            desc = t.get("description", "").replace("|", "\\|")
            run = t.get("run", "")
            run = f"`{run}`" if run else ""
            run = run.replace("|", "\\|")
            replaces = t.get("replaces", "").replace("|", "\\|")
            lines.append(f"| {name} | {desc} | {run} | {replaces} |")
        lines.append("")  # 카테고리 사이 빈 줄

    return "\n".join(lines).rstrip()


def render_readme(menu):
    """README가 없으면 기본 골격 생성, 있으면 마커 사이만 교체."""
    if os.path.isfile(README):
        with open(README, encoding="utf-8") as f:
            content = f.read()
        if START in content and END in content:
            pre = content.split(START)[0]
            post = content.split(END)[1]
            return f"{pre}{START}\n\n{menu}\n\n{END}{post}"
    # 새로 생성
    return TEMPLATE.format(menu=menu)


TEMPLATE = """# just-this

> 여기저기 검색하고, 광고 보고, 결제하고, 시간 버리는 짓 그만.
> 딱 필요한 도구만 직접 만들어서 차곡차곡 박아두는 개인 창고.

매번 웹에서 찾아 헤매던 유틸들을 한 곳에. 새 도구 추가는
[CONVENTIONS.md](./CONVENTIONS.md) 규칙대로 폴더 + `tool.json` 만들고
`python index.py` 한 번이면 아래 메뉴가 자동 갱신됨.

## 메뉴

<!-- TOOLS:START -->

{menu}

<!-- TOOLS:END -->

## 새 도구 추가
[CONVENTIONS.md](./CONVENTIONS.md) 참고. 요약:
1. 폴더 만들고 코드 + `tool.json` 넣기
2. `python index.py` 실행
3. 커밋
"""


def main():
    tools = load_tools()
    menu = build_menu(tools)
    new_content = render_readme(menu)

    if "--check" in sys.argv:
        current = ""
        if os.path.isfile(README):
            with open(README, encoding="utf-8") as f:
                current = f.read()
        if current.strip() != new_content.strip():
            print("README 갱신 필요. `python index.py` 실행할 것.", file=sys.stderr)
            sys.exit(1)
        print("README 최신 상태.")
        return

    with open(README, "w", encoding="utf-8") as f:
        f.write(new_content)
    print(f"README 갱신 완료 — 도구 {len(tools)}개")


if __name__ == "__main__":
    main()
