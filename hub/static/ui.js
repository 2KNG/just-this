/* ─────────────────────────────────────────────────────────────────────────────
   just-this 공용 UI 스크립트 (ui.js) — 허브가 /static/ui.js 로 서빙.

   도구 페이지 <head> 에서 동기 로드 → 테마를 첫 페인트 전에 적용(깜빡임 없음).
   DOM 준비되면:
     · 상단 nav 채우기(/api/tools) + 현재 도구 표시 + 테마 토글 + ⌘K 버튼
     · 페이지 제목 앞에 도구 아이콘
     · .drop 영역에 업로드 아이콘 + 페이지 밖으로 파일 떨궈도 브라우저가
       파일을 열어버리지 않게 막고, 드롭존이 하나면 거기로 전달
     · .status 가 err/ok 로 바뀌면 토스트로도 알림 (화면 밖에 있을 때 놓치지 않게)
   전역: window.JT = { toast, setTheme, openPalette, tools }
   ───────────────────────────────────────────────────────────────────────────── */
(function () {
  "use strict";
  var KEY = "jt-theme";            // "light" | "dark" | (없음 = 시스템)
  var root = document.documentElement;
  var mq = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;

  function stored() { try { return localStorage.getItem(KEY); } catch (_) { return null; } }
  function effective() { var s = stored(); return s === "light" || s === "dark" ? s : (mq && mq.matches ? "dark" : "light"); }
  function applyTheme() { root.setAttribute("data-theme", effective()); }
  applyTheme();
  if (mq && mq.addEventListener) mq.addEventListener("change", function () { if (!stored()) applyTheme(); syncThemeBtn(); });

  function setTheme(t) {
    try { if (t) localStorage.setItem(KEY, t); else localStorage.removeItem(KEY); } catch (_) {}
    applyTheme(); syncThemeBtn();
  }

  // ── 아이콘 (Lucide 스타일 라인 아이콘, 24 그리드) ──
  var P = {
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    moon: '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    upload: '<path d="M12 15V3M7 8l5-5 5 5"/><path d="M20 15v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-4"/>',
    image: '<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="9" cy="9" r="2"/><path d="m21 15-4.5-4.5L6 21"/>',
    crop: '<path d="M6 2v14a2 2 0 0 0 2 2h14"/><path d="M18 22V8a2 2 0 0 0-2-2H2"/>',
    files: '<path d="M15 2H8a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h9a2 2 0 0 0 2-2V6z"/><path d="M15 2v4h4"/><path d="M3 7v13a2 2 0 0 0 2 2h10"/>',
    film: '<rect x="2" y="4" width="20" height="16" rx="3"/><path d="M7 4v16M17 4v16M2 9h5M2 15h5M17 9h5M17 15h5"/>',
    play: '<rect x="2" y="5" width="20" height="14" rx="4"/><path d="m10 9 5 3-5 3z"/>',
    code: '<path d="m16 18 6-6-6-6M8 6l-6 6 6 6"/>',
    qr: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><path d="M14 14h3v3M21 14v.01M14 21h3M21 17v4h-4"/>',
    box: '<path d="M21 8 12 3 3 8v8l9 5 9-5z"/><path d="m3 8 9 5 9-5M12 13v8"/>',
    x: '<path d="M18 6 6 18M6 6l12 12"/>'
  };
  function svg(name) {
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + (P[name] || P.box) + "</svg>";
  }
  // 도구별 아이콘 + 그라디언트 (허브 카드·nav·팔레트 공통)
  var TOOL_ICON = {
    imgconv: ["image", "#7c3aed", "#c084fc"],
    webcrop: ["crop", "#0f766e", "#2dd4bf"],
    pdftools: ["files", "#dc2626", "#fb7185"],
    vidconv: ["film", "#ea580c", "#fbbf24"],
    ytdl: ["play", "#e11d48", "#f97316"],
    devkit: ["code", "#1d4ed8", "#38bdf8"],
    qr: ["qr", "#334155", "#94a3b8"]
  };
  function toolIcon(slug) {
    var t = TOOL_ICON[slug] || ["box", "", ""];
    var style = t[1] ? ' style="--tc1:' + t[1] + ";--tc2:" + t[2] + '"' : "";
    return '<span class="jt-ticon"' + style + ">" + svg(t[0]) + "</span>";
  }

  function currentSlug() {
    var seg = (location.pathname.split("/").filter(Boolean)[0]) || "";
    return seg;
  }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }

  // ── 토스트 ──
  var toastBox;
  function toast(msg, type, ms) {
    if (!msg) return;
    if (!toastBox) {
      toastBox = document.createElement("div");
      toastBox.className = "jt-toasts";
      toastBox.setAttribute("role", "status");
      toastBox.setAttribute("aria-live", "polite");
      document.body.appendChild(toastBox);
    }
    var el = document.createElement("div");
    el.className = "jt-toast" + (type ? " " + type : "");
    el.innerHTML = '<span class="jt-dot"></span><span class="jt-msg"></span><button type="button" aria-label="닫기">×</button>';
    el.querySelector(".jt-msg").textContent = msg;
    var close = function () { el.classList.add("out"); setTimeout(function () { el.remove(); }, 200); };
    el.querySelector("button").onclick = close;
    toastBox.appendChild(el);
    while (toastBox.children.length > 4) toastBox.firstChild.remove();
    setTimeout(close, ms || (type === "err" ? 6000 : 3200));
    return el;
  }

  // ── 도구 목록 ──
  var toolsPromise = null;
  function tools() {
    if (!toolsPromise) {
      toolsPromise = fetch("/api/tools").then(function (r) { return r.ok ? r.json() : { tools: [] }; })
        .then(function (d) { return (d.tools || []).filter(function (t) { return t._open; }); })
        .catch(function () { return []; });
    }
    return toolsPromise;
  }

  // ── 명령 팔레트 ──
  var palEl = null;
  function openPalette() {
    if (palEl) return;
    tools().then(function (list) {
      var back = document.createElement("div");
      back.className = "jt-palette-back";
      back.innerHTML = '<div class="jt-palette" role="dialog" aria-modal="true" aria-label="도구 이동">' +
        '<input type="text" placeholder="도구로 이동… (이름·설명·태그)" aria-label="도구 검색" autocomplete="off">' +
        '<ul role="listbox"></ul>' +
        '<div class="jt-pal-foot"><span><kbd>↑</kbd> <kbd>↓</kbd> 이동</span><span><kbd>Enter</kbd> 열기</span><span><kbd>Esc</kbd> 닫기</span></div></div>';
      document.body.appendChild(back);
      palEl = back;
      var input = back.querySelector("input"), ul = back.querySelector("ul"), sel = 0, shown = [];
      var home = { slug: "", name: "대시보드", short: "홈", description: "모든 도구 한눈에", _open: "/", tags: ["home", "hub"] };
      var all = [home].concat(list);
      function render() {
        var q = input.value.trim().toLowerCase();
        shown = all.filter(function (t) {
          if (!q) return true;
          return [t.name, t.short, t.slug, t.description, (t.tags || []).join(" ")].join(" ").toLowerCase().indexOf(q) >= 0;
        });
        if (sel >= shown.length) sel = Math.max(0, shown.length - 1);
        ul.innerHTML = shown.length ? shown.map(function (t, i) {
          return '<li role="option"' + (i === sel ? ' class="sel" aria-selected="true"' : "") + '><a href="' + esc(t._open) + '">' +
            (t.slug ? toolIcon(t.slug) : '<span class="jt-ticon">' + svg("box") + "</span>") +
            "<span><strong>" + esc(t.name) + "</strong><small>" + esc(t.description) + "</small></span></a></li>";
        }).join("") : '<li class="jt-pal-empty">일치하는 도구 없음</li>';
        var s = ul.querySelector(".sel"); if (s && s.scrollIntoView) s.scrollIntoView({ block: "nearest" });
      }
      function close() { back.remove(); palEl = null; }
      input.addEventListener("input", function () { sel = 0; render(); });
      input.addEventListener("keydown", function (e) {
        if (e.key === "ArrowDown") { sel = Math.min(shown.length - 1, sel + 1); render(); e.preventDefault(); }
        else if (e.key === "ArrowUp") { sel = Math.max(0, sel - 1); render(); e.preventDefault(); }
        else if (e.key === "Enter") { if (shown[sel]) location.href = shown[sel]._open; }
        else if (e.key === "Escape") { close(); }
      });
      back.addEventListener("mousedown", function (e) { if (e.target === back) close(); });
      render();
      input.focus();
    });
  }

  // ── 테마 버튼 ──
  var themeBtn = null;
  function syncThemeBtn() {
    if (!themeBtn) return;
    var dark = effective() === "dark";
    themeBtn.innerHTML = svg(dark ? "sun" : "moon");
    themeBtn.title = dark ? "밝은 테마로" : "어두운 테마로";
    themeBtn.setAttribute("aria-label", themeBtn.title);
  }

  function enhanceNav() {
    var nav = document.querySelector("nav.nav");
    if (!nav) return;
    var brand = nav.querySelector(".nav-brand");
    if (brand && !brand.querySelector(".jt-mark")) {
      brand.innerHTML = '<span class="jt-mark">JT</span><span class="jt-brand-text">' + esc(brand.textContent.trim() || "just-this") + "</span>";
    }
    var links = nav.querySelector(".nav-links");
    var slug = currentSlug();
    if (links && !links.children.length) {
      tools().then(function (list) {
        if (links.children.length) return;   // 페이지가 자체적으로 채웠으면 건드리지 않음
        list.forEach(function (t) {
          var a = document.createElement("a");
          a.href = t._open; a.textContent = t.short || t.name;
          if (t._open_blank) { a.target = "_blank"; a.rel = "noopener"; }
          if (t.slug === slug) a.setAttribute("aria-current", "page");
          links.appendChild(a);
        });
        var cur = links.querySelector('[aria-current="page"]');
        if (cur && cur.scrollIntoView) cur.scrollIntoView({ block: "nearest", inline: "center" });
      });
    }
    if (!nav.querySelector(".jt-nav-actions")) {
      var box = document.createElement("div");
      box.className = "jt-nav-actions";
      var k = /Mac|iPhone|iPad/.test(navigator.platform || "") ? "⌘K" : "Ctrl K";
      box.innerHTML = '<button type="button" class="jt-iconbtn jt-cmdk-btn" title="도구 이동 (' + k + ')" aria-label="도구 이동">' +
        svg("search") + '<span class="jt-cmdk-label">이동</span><span class="jt-kbd">' + k + "</span></button>" +
        '<button type="button" class="jt-iconbtn jt-theme-btn"></button>';
      var right = nav.querySelector(".nav-right");
      if (right) nav.insertBefore(box, right); else nav.appendChild(box);
      box.querySelector(".jt-cmdk-btn").onclick = openPalette;
      themeBtn = box.querySelector(".jt-theme-btn");
      themeBtn.onclick = function () { setTheme(effective() === "dark" ? "light" : "dark"); };
      syncThemeBtn();
    }
  }

  function enhancePagehead() {
    var h1 = document.querySelector(".pagehead h1");
    var slug = currentSlug();
    if (h1 && slug && !h1.querySelector(".jt-ticon")) h1.insertAdjacentHTML("afterbegin", toolIcon(slug));
  }

  function enhanceDrops() {
    var drops = [].slice.call(document.querySelectorAll(".drop"));
    drops.forEach(function (d) {
      if (!d.querySelector(".jt-drop-ico")) d.insertAdjacentHTML("afterbegin", '<span class="jt-drop-ico">' + svg("upload") + "</span>");
    });
    // 드롭존 밖에 파일을 떨구면 브라우저가 그 파일을 열어서 작업 중이던 화면이 날아간다 → 막는다.
    var depth = 0;
    function hasFiles(e) { var t = e.dataTransfer && e.dataTransfer.types; return t && [].indexOf.call(t, "Files") >= 0; }
    function visibleDrops() { return drops.filter(function (d) { return d.offsetParent !== null; }); }
    window.addEventListener("dragenter", function (e) { if (!hasFiles(e)) return; depth++; if (visibleDrops().length) document.body.classList.add("jt-dragging"); });
    window.addEventListener("dragleave", function (e) { if (!hasFiles(e)) return; depth = Math.max(0, depth - 1); if (!depth) document.body.classList.remove("jt-dragging"); });
    window.addEventListener("dragover", function (e) { if (hasFiles(e)) e.preventDefault(); });
    window.addEventListener("drop", function (e) {
      depth = 0; document.body.classList.remove("jt-dragging");
      if (!hasFiles(e)) return;
      var inside = e.target.closest && e.target.closest(".drop");
      if (inside) return;                    // 드롭존 자체 핸들러가 처리
      e.preventDefault();
      var vis = visibleDrops();
      if (vis.length !== 1) { if (vis.length) toast("파일을 점선 영역에 놓아주세요", ""); return; }
      // 화면에 드롭존이 하나면 그쪽 input 으로 넘겨준다 (change 이벤트 → 기존 도구 로직 그대로)
      var input = vis[0].querySelector('input[type="file"]');
      if (!input) return;
      try {
        var dt = new DataTransfer();
        var files = [].slice.call(e.dataTransfer.files);
        if (!input.multiple) files = files.slice(0, 1);
        files.forEach(function (f) { dt.items.add(f); });
        input.files = dt.files;
        input.dispatchEvent(new Event("change", { bubbles: true }));
      } catch (_) { toast("파일을 점선 영역에 놓아주세요", ""); }
    });
  }

  // .status 가 에러/완료로 바뀌면, 그 요소가 화면 밖일 때만 토스트로 알림
  function watchStatus() {
    if (!window.MutationObserver) return;
    var last = new WeakMap();
    var obs = new MutationObserver(function (muts) {
      muts.forEach(function (m) {
        var el = m.target.nodeType === 1 ? m.target : m.target.parentElement;
        if (!el || !el.classList) return;
        el = el.closest(".status");
        if (!el) return;
        var kind = el.classList.contains("err") ? "err" : el.classList.contains("ok") ? "ok" : "";
        var text = (el.textContent || "").trim();
        var sig = kind + "|" + text;
        if (!kind || !text || last.get(el) === sig) return;
        last.set(el, sig);
        var r = el.getBoundingClientRect();
        var offscreen = r.bottom < 0 || r.top > window.innerHeight || el.offsetParent === null;
        if (offscreen) toast(text, kind);
      });
    });
    obs.observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ["class"] });
  }

  function keys() {
    document.addEventListener("keydown", function (e) {
      if ((e.metaKey || e.ctrlKey) && (e.key === "k" || e.key === "K")) { e.preventDefault(); openPalette(); }
    });
  }

  function init() {
    enhanceNav();
    enhancePagehead();
    enhanceDrops();
    watchStatus();
    keys();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();

  window.JT = { toast: toast, setTheme: setTheme, openPalette: openPalette, tools: tools, toolIcon: toolIcon, svg: svg };
})();
