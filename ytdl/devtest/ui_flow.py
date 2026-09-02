#!/usr/bin/env python3
"""
재생목록 탭 UI 흐름을 Playwright 로 자동 실행 — 붙여넣기 → 목록 → 선택 → 진행 → 결과 받기.
HTML-in-Canvas(drawElement) 실험 기능은 --flag 로 켠다 (Chromium 플래그 --enable-blink-features=CanvasDrawElement).

    pip install playwright && playwright install chromium     # 최초 1회 (레포 requirements 에는 안 넣음)
    python run.py                                              # 허브 (다른 터미널)
    python ytdl/devtest/make_fake_playlist.py --serve          # 가짜 재생목록 (다른 터미널)

    python ytdl/devtest/ui_flow.py                       # 기본 브라우저(플래그 없음) = 폴백 경로
    python ytdl/devtest/ui_flow.py --flag                # drawElement 켜고
    python ytdl/devtest/ui_flow.py --flag --mobile       # 390px 모바일 뷰포트
    python ytdl/devtest/ui_flow.py --headed              # 창 띄워서 눈으로 보기

콘솔 에러/페이지 에러가 하나라도 있으면 exit 1. 스크린샷은 --shots 폴더(기본 ytdl/devtest/_shots).
"""

import argparse
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))

# 캔버스 무대(#pstage) 상태 — drawElement 지원이면 보여야(높이>100, 캔버스 자식 있음), 미지원이면 공간조차 없어야 한다
STAGE_JS = """() => { const e = document.getElementById('pstage'); if (!e) return null;
  const r = e.getBoundingClientRect(); return {hidden: e.hidden, h: r.height, disp: getComputedStyle(e).display,
  kids: (e.querySelector('canvas') || {children: []}).children.length}; }"""
# 600ms 동안 requestAnimationFrame 호출 수 — 작업이 끝난 뒤엔 0 이어야 한다(배터리)
RAF_JS = """() => new Promise(res => { let c = 0; const o = window.requestAnimationFrame;
  window.requestAnimationFrame = f => { c++; return o.call(window, f); };
  setTimeout(() => { window.requestAnimationFrame = o; res(c); }, 600); })"""


def stage_check(pg, sup, errs, when):
    s = pg.evaluate(STAGE_JS)
    if s is None:
        print(f"스테이지({when}): #pstage 없음")
        return
    ok = (not s["hidden"] and s["h"] > 100 and s["kids"] > 0) if sup else (s["hidden"] and s["disp"] == "none" and s["h"] == 0)
    print(f"스테이지({when}):", s, "OK" if ok else "!! 기대와 다름")
    if not ok:
        errs.append(f"stage[{when}]: {s}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000/ytdl/")
    ap.add_argument("--playlist", default="http://127.0.0.1:8811/list.html")
    ap.add_argument("--flag", action="store_true", help="--enable-blink-features=CanvasDrawElement")
    ap.add_argument("--mobile", action="store_true", help="390x844, 터치")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--uncheck", type=int, default=-1, help="n번째(0-based) 곡 체크 해제 (선택 다운로드 확인)")
    ap.add_argument("--shots", default=os.path.join(HERE, "_shots"))
    ap.add_argument("--chromium", default=os.environ.get("PW_CHROMIUM"), help="Chromium 실행파일 (기본: playwright 내장)")
    a = ap.parse_args()
    os.makedirs(a.shots, exist_ok=True)
    tag = ("flag" if a.flag else "noflag") + ("-mobile" if a.mobile else "-desktop")

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        launch = {"headless": not a.headed, "args": ["--enable-blink-features=CanvasDrawElement"] if a.flag else []}
        if a.chromium:
            launch["executable_path"] = a.chromium
        b = p.chromium.launch(**launch)
        ctx = b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True, accept_downloads=True) \
            if a.mobile else b.new_context(viewport={"width": 1200, "height": 900}, accept_downloads=True)
        pg = ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append("pageerror: " + str(e)))
        # favicon.ico 404 는 허브에 파비콘이 없어서 나는 것 — 실패로 치지 않음
        pg.on("console", lambda m: errs.append("console." + m.type + ": " + m.text + " @ " + (m.location or {}).get("url", ""))
              if m.type == "error" and not (m.location or {}).get("url", "").endswith("/favicon.ico") else None)

        pg.goto(a.base)
        sup = pg.evaluate("['drawElementImage','drawElement'].some(n => n in CanvasRenderingContext2D.prototype)")   # 141 / 151+ 이름
        print("drawElement 지원:", sup)
        pg.click("#tabs button[data-t=playlist]")
        pg.fill("#purl", a.playlist)
        pg.click("#pinfoBtn")
        pg.wait_for_selector("#tracks .tr", timeout=60000)
        n = pg.locator("#tracks .tr").count()
        print(f"목록: {n}곡 · {pg.text_content('#pmeta')}")
        if a.uncheck < n and a.uncheck >= 0 and n > 1:
            pg.locator("#tracks .tr").nth(a.uncheck).locator("input").uncheck()
        pg.screenshot(path=os.path.join(a.shots, f"{tag}-1-list.png"), full_page=True)

        pg.click("#pgoBtn")
        pg.wait_for_selector("#pjob:not(.hide)", timeout=10000)
        pg.wait_for_timeout(700)                                   # 카드 슬라이드 인이 끝난 뒤 찍기
        stage_check(pg, sup, errs, "진행 중")
        pg.screenshot(path=os.path.join(a.shots, f"{tag}-2-running.png"), full_page=True)
        pg.wait_for_selector("#presult:not(.hide)", timeout=180000)
        print("완료:", pg.text_content("#pcount"), "|", pg.text_content("#pjstatus"))
        stage_check(pg, sup, errs, "완료")
        n = pg.evaluate(RAF_JS)
        print("완료 후 600ms rAF 호출:", n)
        if n:
            errs.append(f"rAF still running after done: {n}")
        pg.screenshot(path=os.path.join(a.shots, f"{tag}-3-done.png"), full_page=True)
        print("가로 스크롤 없음:", pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))

        with pg.expect_download(timeout=30000) as dl:
            pg.click("#presult")
        d = dl.value
        path = os.path.join(a.shots, f"{tag}-" + d.suggested_filename)
        d.save_as(path)
        names = zipfile.ZipFile(path).namelist() if path.endswith(".zip") else [os.path.basename(path)]
        print("다운로드:", d.suggested_filename, "→", names)

        # 새로고침 후 이어받기 (localStorage 에 job id)
        pg.goto(a.base)
        pg.wait_for_selector("#presult:not(.hide)", timeout=15000)
        print("새로고침 후 결과 버튼 복원:", pg.get_attribute("#tabs button.sel", "data-t") == "playlist")
        stage_check(pg, sup, errs, "새로고침 복원")
        pg.screenshot(path=os.path.join(a.shots, f"{tag}-4-restored.png"), full_page=True)
        b.close()

    print("에러:", errs or "없음")
    print("스크린샷:", a.shots)
    sys.exit(1 if errs else 0)


if __name__ == "__main__":
    main()
