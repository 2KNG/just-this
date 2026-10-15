#!/usr/bin/env python3
"""UI 스모크: 허브 + 7개 도구를 라이트/다크·데스크톱/모바일로 열어 JS 에러·nav·아이콘을 검사하고 스크린샷 저장."""
import os
import sys

from playwright.sync_api import sync_playwright

BASE = os.environ.get("BASE", "http://127.0.0.1:8765")
OUT = sys.argv[1] if len(sys.argv) > 1 else "/tmp/jt_shots"
os.makedirs(OUT, exist_ok=True)
PAGES = ["", "imgconv", "webcrop", "pdftools", "vidconv", "ytdl", "devkit", "qr"]

fails = []
with sync_playwright() as p:
    b = p.chromium.launch()
    for theme in ("light", "dark"):
        for vp_name, vp in (("desk", {"width": 1360, "height": 900}), ("mobile", {"width": 390, "height": 844})):
            ctx = b.new_context(viewport=vp, color_scheme=theme, device_scale_factor=1)
            for slug in PAGES:
                pg = ctx.new_page()
                errs = []
                pg.on("pageerror", lambda e, errs=errs: errs.append(str(e)))
                pg.on("console", lambda m, errs=errs: errs.append("console: " + m.text) if m.type == "error" else None)
                pg.goto(f"{BASE}/{slug}/" if slug else BASE + "/", wait_until="networkidle")
                pg.wait_for_timeout(250)
                info = pg.evaluate("""() => ({
                    theme: document.documentElement.dataset.theme,
                    navLinks: document.querySelectorAll('.nav-links a').length,
                    current: (document.querySelector('.nav-links a[aria-current=page]')||{}).textContent||'',
                    actions: !!document.querySelector('.jt-nav-actions'),
                    ticon: !!document.querySelector('.pagehead .jt-ticon, .card .jt-ticon'),
                    hscroll: document.documentElement.scrollWidth > window.innerWidth + 1,
                })""")
                name = f"{slug or 'hub'}_{theme}_{vp_name}"
                pg.screenshot(path=os.path.join(OUT, name + ".png"), full_page=False)
                problems = []
                if errs: problems.append(f"js errors: {errs[:3]}")
                if info["theme"] != theme: problems.append(f"theme={info['theme']}")
                if info["navLinks"] < 7: problems.append(f"navLinks={info['navLinks']}")
                if slug and not info["current"]: problems.append("no aria-current")
                if not info["actions"]: problems.append("no nav actions")
                if not info["ticon"]: problems.append("no tool icon")
                if info["hscroll"]: problems.append("horizontal overflow")
                print(f"{'FAIL' if problems else 'ok  '} {name:28s} {info}  {problems or ''}")
                if problems: fails.append((name, problems))
                pg.close()
            ctx.close()
    # ⌘K 팔레트 + 테마 토글 동작
    ctx = b.new_context(viewport={"width": 1280, "height": 860}, color_scheme="light")
    pg = ctx.new_page()
    pg.goto(BASE + "/qr/", wait_until="networkidle")
    pg.keyboard.press("Control+k")
    pg.wait_for_selector(".jt-palette")
    pg.keyboard.type("pdf")
    pg.wait_for_timeout(150)
    n = pg.locator(".jt-palette li a").count()
    pg.screenshot(path=os.path.join(OUT, "palette.png"))
    with pg.expect_navigation():
        pg.keyboard.press("Enter")
    print("palette results for 'pdf':", n, "-> navigated to", pg.url)
    if n < 1 or "/qr/" in pg.url: fails.append(("palette", ["no nav"]))
    pg.click(".jt-theme-btn")
    t = pg.evaluate("document.documentElement.dataset.theme")
    pg.reload(wait_until="networkidle")
    t2 = pg.evaluate("document.documentElement.dataset.theme")
    print("theme toggle ->", t, "persist after reload ->", t2)
    if t != "dark" or t2 != "dark": fails.append(("theme", [t, t2]))
    # 상태 배지(에러) 렌더 확인 — QR 생성 빈값
    pg.goto(BASE + "/qr/", wait_until="networkidle")
    pg.click("#gen")
    pg.wait_for_timeout(200)
    cls = pg.evaluate("document.querySelector('#gs').className")
    pg.screenshot(path=os.path.join(OUT, "qr_err_dark.png"))
    print("qr empty-gen status class:", cls)
    ctx.close()
    b.close()

print("\nFAILS:", fails if fails else "none")
sys.exit(1 if fails else 0)
