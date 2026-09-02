#!/usr/bin/env python3
"""
캔버스 무대(PlStage) 경계 사례 회귀 테스트 — 리뷰에서 실측된 결함 4가지가 재발하지 않는지 본다.
플래그 켠 크롬(HTML-in-Canvas)에서만 의미 있음. 미지원 브라우저면 무대가 없으니 "해당 없음"으로 통과.

    python run.py                                          # 허브 (다른 터미널)
    python ytdl/devtest/make_fake_playlist.py --serve      # 가짜 재생목록 (다른 터미널)
    python ytdl/devtest/stage_edge.py [--chromium "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"]

  ① 새 작업 시작 → 이전 작업의 진행 링(100%)이 그대로 남지 않고 0 근처에서 다시 시작
  ② 폴링 실패(status 요청 차단) → DOM 은 "상태 확인 실패", 무대의 rAF 도 멈춤(디스크가 계속 돌면 안 됨)
  ③ 진행 중 "단일 영상" 탭으로 전환 → 무대가 안 보이는 동안 rAF 0, 돌아오면 재개
  ④ 끝 상태에서 창 폭이 바뀜 → 다시 그려짐(낡은 프레임이 영구히 남으면 안 됨)
콘솔/페이지 에러 또는 검사 실패가 하나라도 있으면 exit 1.
"""

import argparse
import math
import os
import sys

# drawElementImage/drawElement 호출 수와 진행 링(−π/2 에서 시작하는 arc)의 끝각을 기록하는 훅
HOOK_JS = """() => {
  const P = CanvasRenderingContext2D.prototype, name = ['drawElementImage', 'drawElement'].find(n => n in P);
  window.__st = {draws: 0, ring: null};
  if (name) { const o = P[name]; P[name] = function () { window.__st.draws++; return o.apply(this, arguments); }; }
  const arc = P.arc; P.arc = function (x, y, r, s, e) { if (Math.abs(s + Math.PI / 2) < 1e-6) window.__st.ring = (e - s) / (2 * Math.PI); return arc.apply(this, arguments); };
}"""
RAF_JS = """() => new Promise(res => { let c = 0; const o = window.requestAnimationFrame;
  window.requestAnimationFrame = f => { c++; return o.call(window, f); };
  setTimeout(() => { window.requestAnimationFrame = o; res(c); }, 600); })"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000/ytdl/")
    ap.add_argument("--playlist", default="http://127.0.0.1:8811/list.html")
    ap.add_argument("--chromium", default=os.environ.get("PW_CHROMIUM"), help="Chromium/Chrome 실행파일 (기본: playwright 내장)")
    ap.add_argument("--headed", action="store_true")
    a = ap.parse_args()

    from playwright.sync_api import sync_playwright
    errs, notes = [], []

    def check(name, ok, detail=""):
        print(("OK  " if ok else "FAIL"), name, detail)
        if not ok:
            errs.append(f"{name}: {detail}")

    with sync_playwright() as p:
        launch = {"headless": not a.headed, "args": ["--enable-blink-features=CanvasDrawElement"]}
        if a.chromium:
            launch["executable_path"] = a.chromium
        b = p.chromium.launch(**launch)
        pg = b.new_context(viewport={"width": 1200, "height": 900}).new_page()
        pg.on("pageerror", lambda e: errs.append("pageerror: " + str(e)))
        # favicon 404 와, ② 에서 테스트가 일부러 차단하는 status 요청의 ERR_FAILED 는 실패로 치지 않음
        pg.on("console", lambda m: errs.append("console.error: " + m.text + " @ " + (m.location or {}).get("url", ""))
              if m.type == "error" and not (m.location or {}).get("url", "").endswith("/favicon.ico")
              and not ("api/playlist/status/" in (m.location or {}).get("url", "") and "ERR_FAILED" in m.text) else None)

        pg.goto(a.base)
        sup = pg.evaluate("['drawElementImage','drawElement'].some(n => n in CanvasRenderingContext2D.prototype)")
        print("drawElement 지원:", sup)
        if not sup:
            print("무대 없음 — 해당 없음으로 종료")
            b.close(); sys.exit(0)
        pg.evaluate(HOOK_JS)
        pg.click("#tabs button[data-t=playlist]")
        pg.fill("#purl", a.playlist)
        pg.click("#pinfoBtn")
        pg.wait_for_selector("#tracks .tr", timeout=60000)

        def run_job():
            pg.click("#pgoBtn")
            pg.wait_for_selector("#pjob:not(.hide)", timeout=10000)
            pg.wait_for_selector("#presult:not(.hide)", timeout=180000)

        # ── 작업 1 완주 → 링 100% ──
        run_job()
        pg.wait_for_timeout(300)
        check("작업1 완료 후 링 100%", (pg.evaluate("window.__st.ring") or 0) > 0.99, str(pg.evaluate("window.__st.ring")))

        # ① 새 작업 시작 직후 링이 0 근처여야 한다 (리셋 안 되면 이전 100% 에서 거꾸로 내려옴 ≈0.6~0.9).
        #    링이 0 이면 진행 arc 를 아예 안 그리므로 훅 값을 비우고 시작 → null 또는 0.2 미만이 정상
        pg.evaluate("window.__st.ring = null")
        pg.click("#pgoBtn")
        pg.wait_for_function("document.querySelector('#pcount').textContent.startsWith('0 /')", timeout=15000)   # 새 작업의 첫 렌더
        pg.wait_for_timeout(120)
        ring = pg.evaluate("window.__st.ring")
        check("① 새 작업 시작 직후 링 리셋", ring is None or ring < 0.2, f"ring={ring}")
        pg.wait_for_selector("#presult:not(.hide)", timeout=180000)

        # ② 폴링 실패 → rAF 정지
        pg.route("**/api/playlist/status/**", lambda r: r.abort())
        pg.click("#pgoBtn")
        pg.wait_for_function("document.querySelector('#pjstatus').textContent.includes('상태 확인 실패')", timeout=15000)
        pg.wait_for_timeout(200)
        n = pg.evaluate(RAF_JS)
        check("② 폴링 실패 후 rAF 정지", n == 0, f"rAF/600ms={n}")
        pg.unroute("**/api/playlist/status/**")
        pg.wait_for_timeout(6000)   # 서버 쪽 버려진 작업이 끝나 동시 작업 한도(2)를 비울 때까지

        # ③ 진행 중 탭 전환 → rAF 0, 복귀 → 재개  (새 작업이 running 으로 그려진 직후 = 취소 버튼 활성·결과 버튼 숨김·상태줄 빈 문자열)
        pg.click("#pgoBtn")
        pg.wait_for_function("!document.querySelector('#pcancel').disabled && document.querySelector('#presult').classList.contains('hide')", timeout=20000)
        pg.wait_for_timeout(200)
        pg.click("#tabs button[data-t=single]")
        pg.wait_for_timeout(150)
        n = pg.evaluate(RAF_JS)
        check("③ 다른 탭에서 rAF 정지", n == 0, f"rAF/600ms={n}")
        pg.click("#tabs button[data-t=playlist]")
        pg.wait_for_timeout(150)
        still = pg.evaluate("document.querySelector('#presult').classList.contains('hide')")
        if still:
            n = pg.evaluate(RAF_JS)
            check("③ 탭 복귀 후 rAF 재개", n > 0, f"rAF/600ms={n}")
        else:
            notes.append("③ 복귀 검사는 작업이 이미 끝나 생략 (가짜 목록이 너무 빨리 끝남)")
        pg.wait_for_selector("#presult:not(.hide)", timeout=180000)
        pg.wait_for_timeout(400)
        n = pg.evaluate(RAF_JS)
        check("완료 후 rAF 0", n == 0, f"rAF/600ms={n}")

        # ④ 끝 상태에서 폭 변경 → 다시 그려져야 한다
        before = pg.evaluate("window.__st.draws")
        pg.set_viewport_size({"width": 420, "height": 900})
        pg.wait_for_timeout(500)
        after = pg.evaluate("window.__st.draws")
        check("④ 끝 상태 리사이즈 후 재그리기", after - before >= 2, f"카드 그리기 {before}→{after}")
        h = pg.evaluate("document.getElementById('pstage').getBoundingClientRect().height")
        check("④ 리사이즈 후 무대 높이 폰 기준(≥150)", h >= 150, f"h={h}")
        b.close()

    for x in notes:
        print("메모:", x)
    print("에러:", errs or "없음")
    sys.exit(1 if errs else 0)


if __name__ == "__main__":
    main()
