#!/usr/bin/env python3
"""
ytdl — 유튜브(및 yt-dlp 지원 사이트) 영상/오디오 추출·구간 자르기 웹앱.

  1) URL 입력 → 정보 가져오기(제목/길이/화질 목록)
  2) 옵션: 화질 / 오디오만(mp3) / 구간 자르기(시작~끝) / 자막
  3) 다운로드 → 서버가 yt-dlp 로 받아(필요시 ffmpeg 병합/추출) 파일로 내려줌

ffmpeg 는 시스템에 있으면 그걸, 없으면 pip imageio-ffmpeg 정적 빌드를 쓴다.
※ 인터넷(유튜브 접속)이 되는 환경에서만 실제 다운로드가 동작한다.
"""

import os
import re
import shutil
import tempfile
import threading
import time
import uuid
import zipfile
from urllib.parse import quote

from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

import yt_dlp
from yt_dlp.utils import download_range_func

HERE = os.path.dirname(os.path.abspath(__file__))
DL_ROOT = os.path.join(tempfile.gettempdir(), "ytdl_downloads")
os.makedirs(DL_ROOT, exist_ok=True)
TTL = 60 * 30

app = FastAPI(title="ytdl")


def ffmpeg_dir():
    """yt-dlp 에 넘길 ffmpeg 위치(디렉터리). 시스템 우선, 없으면 imageio-ffmpeg."""
    sys_ff = shutil.which("ffmpeg")
    if sys_ff:
        return os.path.dirname(sys_ff)
    import imageio_ffmpeg
    exe = imageio_ffmpeg.get_ffmpeg_exe()
    bindir = os.path.join(tempfile.gettempdir(), "jt_ffbin")
    os.makedirs(bindir, exist_ok=True)
    name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    link = os.path.join(bindir, name)
    if not os.path.exists(link):
        try:
            os.symlink(exe, link)
        except OSError:
            shutil.copy(exe, link)
    return bindir


FFDIR = ffmpeg_dir()


def cleanup():
    now = time.time()
    for d in os.listdir(DL_ROOT):
        p = os.path.join(DL_ROOT, d)
        try:
            if os.path.isdir(p) and now - os.path.getmtime(p) > TTL:
                shutil.rmtree(p, ignore_errors=True)
        except OSError:
            pass


def valid_url(u):
    return bool(re.match(r"^https?://", (u or "").strip()))


@app.get("/", response_class=HTMLResponse)
def index():
    with open(os.path.join(HERE, "static", "index.html"), encoding="utf-8") as f:
        return f.read()


@app.get("/healthz")
def healthz():
    return {"ok": True, "ffmpeg_dir": FFDIR, "yt_dlp": yt_dlp.version.__version__}


@app.post("/api/info")
async def info(url: str = Form(...)):
    if not valid_url(url):
        raise HTTPException(400, "http(s) URL 을 넣어주세요")
    opts = {"quiet": True, "no_warnings": True, "skip_download": True,
            "noplaylist": True, "ffmpeg_location": FFDIR}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            d = ydl.extract_info(url, download=False)
    except Exception as e:
        raise HTTPException(400, f"정보 가져오기 실패: {str(e)[:300]}")
    if d.get("entries"):
        d = d["entries"][0]
    heights = sorted({f["height"] for f in d.get("formats", [])
                      if f.get("vcodec") not in (None, "none") and f.get("height")}, reverse=True)
    return JSONResponse({
        "title": d.get("title", ""),
        "uploader": d.get("uploader", ""),
        "duration": d.get("duration", 0),
        "thumbnail": d.get("thumbnail", ""),
        "heights": heights,
    })


def _pick_output(d):
    files = [os.path.join(d, f) for f in os.listdir(d)]
    files = [f for f in files if os.path.isfile(f) and not f.endswith(".part")]
    if not files:
        return None
    return max(files, key=os.path.getsize)


@app.post("/api/download")
async def download(
    url: str = Form(...),
    mode: str = Form("video"),       # video | audio
    height: int = Form(0),           # 0=최고화질
    start: float = Form(0.0),
    end: float = Form(0.0),          # 0=끝까지
    subs: bool = Form(False),
):
    if not valid_url(url):
        raise HTTPException(400, "http(s) URL 을 넣어주세요")
    cleanup()
    dldir = os.path.join(DL_ROOT, str(int(time.time() * 1000)))
    os.makedirs(dldir, exist_ok=True)

    opts = {
        "quiet": True, "no_warnings": True, "noplaylist": True,
        "ffmpeg_location": FFDIR,
        "outtmpl": os.path.join(dldir, "%(title).80B.%(ext)s"),
        "restrictfilenames": True,
        "windowsfilenames": True,
    }
    if mode == "audio":
        opts["format"] = "bestaudio/best"
        opts["postprocessors"] = [{"key": "FFmpegExtractAudio",
                                   "preferredcodec": "mp3", "preferredquality": "192"}]
    else:
        h = int(height) or 9999
        opts["format"] = (f"bestvideo[height<={h}]+bestaudio/best[height<={h}]/best")
        opts["merge_output_format"] = "mp4"
    if subs and mode != "audio":
        opts["writesubtitles"] = True
        opts["writeautomaticsub"] = True
        opts["subtitleslangs"] = ["ko", "en"]
        opts["embedsubtitles"] = True
    if end > start:
        opts["download_ranges"] = download_range_func(None, [(float(start), float(end))])
        opts["force_keyframes_at_cuts"] = True

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
    except Exception as e:
        shutil.rmtree(dldir, ignore_errors=True)
        raise HTTPException(400, f"다운로드 실패: {str(e)[:300]}")

    out = _pick_output(dldir)
    if not out:
        raise HTTPException(400, "결과 파일을 찾지 못함")
    fname = os.path.basename(out)
    disp = f"attachment; filename=\"{re.sub(chr(34), '', fname)}\"; filename*=UTF-8''{quote(fname)}"
    media = "audio/mpeg" if out.endswith(".mp3") else \
        ("video/mp4" if out.endswith(".mp4") else "application/octet-stream")
    return FileResponse(out, media_type=media, headers={"Content-Disposition": disp})


# ─────────────────────────────────────────────────────────────────────────────
# 재생목록 → MP3 일괄 추출
#
# 재생목록은 곡 수만큼 오래 걸려서 한 번의 요청으로 처리하면 타임아웃난다.
# 그래서 작업(job)을 백그라운드 스레드로 돌리고, 프론트가 진행률을 폴링한 뒤
# 다 끝나면 zip(또는 1곡이면 mp3)을 받아가는 구조.
#
#   POST /api/playlist/info          → 목록 훑기 (제목·길이, 다운로드 안 함)
#   POST /api/playlist/start         → 선택한 곡 추출 시작 → job_id
#   GET  /api/playlist/status/{id}   → 진행률 폴링
#   POST /api/playlist/cancel/{id}   → 취소
#   GET  /api/playlist/result/{id}   → 결과 파일 받기
# ─────────────────────────────────────────────────────────────────────────────

MAX_ITEMS = 300        # 한 번에 처리할 최대 곡 수 (그 이상은 잘라서 안내)
MAX_ACTIVE_JOBS = 2    # 동시 진행 작업 수 (개인 서버 과부하 방지)

JOBS = {}
JOBS_LOCK = threading.Lock()

_BAD_CHARS = re.compile(r'[\\/:*?"<>|]|[\x00-\x1f]')


class Canceled(Exception):
    """사용자가 취소 버튼을 눌렀을 때 진행 훅에서 올리는 신호."""


def safe_name(s, maxlen=100):
    """파일명으로 쓸 수 있게 다듬는다. 한글은 살린다(zip 안 이름용)."""
    s = _BAD_CHARS.sub("_", (s or "").replace("\n", " "))
    s = re.sub(r"\s+", " ", s).strip().strip(".")
    return s[:maxlen].strip() or "track"


def flat_entries(url, limit=MAX_ITEMS):
    """재생목록을 훑어 (제목, 항목리스트, 잘렸는지) 반환. 실제 다운로드는 안 한다."""
    opts = {
        "quiet": True, "no_warnings": True, "skip_download": True,
        "noplaylist": False, "extract_flat": "in_playlist",
        "playlistend": limit, "ffmpeg_location": FFDIR,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        d = ydl.extract_info(url, download=False)

    raw = d.get("entries")
    if raw is None:                      # 재생목록이 아니라 영상 하나짜리 URL
        raw = [d]
        title = ""
    else:
        title = d.get("title") or d.get("id") or ""

    items = []
    for e in raw:
        if not e:                        # 비공개·삭제된 항목은 None 으로 온다
            continue
        vid = e.get("id") or ""
        link = e.get("url") or e.get("webpage_url") or (
            f"https://www.youtube.com/watch?v={vid}" if vid else "")
        if not link:
            continue
        items.append({
            "n": len(items) + 1,
            "id": vid,
            "title": e.get("title") or "(제목 없음)",
            "uploader": e.get("uploader") or e.get("channel") or "",
            "duration": e.get("duration") or 0,
            "url": link,
        })
    return title, items, len(items) >= limit


@app.post("/api/playlist/info")
async def playlist_info(url: str = Form(...)):
    if not valid_url(url):
        raise HTTPException(400, "http(s) URL 을 넣어주세요")
    try:
        title, items, truncated = flat_entries(url)
    except Exception as e:
        raise HTTPException(400, f"재생목록 읽기 실패: {str(e)[:300]}")
    if not items:
        raise HTTPException(400, "가져올 수 있는 항목이 없습니다 (비공개 목록인지 확인)")
    return JSONResponse({
        "title": title, "count": len(items), "truncated": truncated,
        "total_duration": sum(i["duration"] or 0 for i in items),
        "items": items,
    })


def job_public(j):
    """프론트에 내보낼 작업 상태(내부 경로·스레드 핸들 제외)."""
    return {
        "id": j["id"], "state": j["state"], "total": j["total"],
        "done": j["done"], "current": j["current"], "pct": j["pct"],
        "failed": j["failed"], "error": j["error"],
        "filename": j["filename"], "ready": bool(j["result"]),
    }


def run_job(job, url, wanted, quality, numbering, tags):
    """백그라운드 스레드 본체 — 곡별로 받아서 mp3 로 변환하고 마지막에 zip 으로 묶는다."""
    dldir = job["dir"]
    try:
        _title, items, _tr = flat_entries(url)
        if wanted:                        # 사용자가 고른 번호만 (1-based)
            items = [i for i in items if i["n"] in wanted]
        if not items:
            raise RuntimeError("선택된 항목이 없습니다")

        job["total"] = len(items)
        results = []                      # (파일경로, zip 안에서 쓸 이름)

        for idx, it in enumerate(items):
            if job["cancel"]:
                raise Canceled()
            job["current"] = it["title"]
            job["pct"] = 0

            def hook(d, _job=job):
                if _job["cancel"]:
                    raise Canceled()
                if d.get("status") == "downloading":
                    total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                    if total:
                        _job["pct"] = min(99, int(d.get("downloaded_bytes", 0) * 100 / total))

            itemdir = os.path.join(dldir, "items", str(idx))
            os.makedirs(itemdir, exist_ok=True)
            opts = {
                "quiet": True, "no_warnings": True, "noplaylist": True,
                "ffmpeg_location": FFDIR,
                "outtmpl": os.path.join(itemdir, "track.%(ext)s"),
                "format": "bestaudio/best",
                "progress_hooks": [hook],
                "postprocessors": [{"key": "FFmpegExtractAudio",
                                    "preferredcodec": "mp3",
                                    "preferredquality": str(quality)}],
            }
            if tags:                      # 제목·아티스트 메타데이터 + 앨범아트(썸네일)
                opts["writethumbnail"] = True
                opts["postprocessors"] += [{"key": "FFmpegMetadata"},
                                           {"key": "EmbedThumbnail"}]
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.download([it["url"]])
            except Canceled:
                raise
            except Exception as e:        # 한 곡이 막혀도 나머지는 계속 간다
                job["failed"].append({"title": it["title"], "reason": str(e)[:200]})
                job["done"] += 1
                continue

            mp3 = next((os.path.join(itemdir, f) for f in sorted(os.listdir(itemdir))
                        if f.endswith(".mp3")), None)
            if not mp3:
                job["failed"].append({"title": it["title"], "reason": "mp3 변환 결과 없음"})
            else:
                prefix = f"{it['n']:02d} - " if numbering else ""
                results.append((mp3, f"{prefix}{safe_name(it['title'])}.mp3"))
            job["done"] += 1
            job["pct"] = 100

        if job["cancel"]:
            raise Canceled()
        if not results:
            raise RuntimeError("받아낸 곡이 없습니다")

        if len(results) == 1:             # 한 곡이면 굳이 압축하지 않는다
            src, name = results[0]
            out = os.path.join(dldir, name)
            shutil.move(src, out)
        else:
            base = safe_name(job["label"] or "playlist", 60)
            out = os.path.join(dldir, f"{base}.zip")
            used = set()
            with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as zf:
                for src, name in results:  # mp3 는 이미 압축돼 있어 무압축 저장
                    stem, ext = os.path.splitext(name)
                    n, name2 = 2, name
                    while name2.lower() in used:
                        name2 = f"{stem} ({n}){ext}"
                        n += 1
                    used.add(name2.lower())
                    zf.write(src, arcname=name2)

        shutil.rmtree(os.path.join(dldir, "items"), ignore_errors=True)
        job["result"] = out
        job["filename"] = os.path.basename(out)
        job["state"] = "done"
    except Canceled:
        job["state"] = "canceled"
        shutil.rmtree(dldir, ignore_errors=True)
    except Exception as e:
        job["state"] = "error"
        job["error"] = str(e)[:300]
        shutil.rmtree(os.path.join(dldir, "items"), ignore_errors=True)
    finally:
        job["current"] = ""


def parse_indexes(s):
    """'1,3,5' → {1,3,5}. 빈 값이면 전체(빈 집합)."""
    out = set()
    for part in (s or "").replace(" ", "").split(","):
        if part.isdigit():
            out.add(int(part))
    return out


@app.post("/api/playlist/start")
async def playlist_start(
    url: str = Form(...),
    indexes: str = Form(""),          # 비우면 전체
    quality: int = Form(320),         # 320(기본, 고음질) | 192 | 128 kbps
    numbering: bool = Form(True),     # 파일명 앞에 순번
    tags: bool = Form(True),          # 메타데이터·앨범아트 심기
    label: str = Form(""),            # zip 파일명에 쓸 재생목록 제목
):
    if not valid_url(url):
        raise HTTPException(400, "http(s) URL 을 넣어주세요")
    if int(quality) not in (128, 192, 320):
        raise HTTPException(400, "음질은 128/192/320 중에서")
    cleanup()

    with JOBS_LOCK:
        active = sum(1 for j in JOBS.values() if j["state"] == "running")
        if active >= MAX_ACTIVE_JOBS:
            raise HTTPException(429, f"이미 {active}개 작업이 돌고 있습니다. 끝나면 다시 시도하세요")
        jid = uuid.uuid4().hex[:12]
        dldir = os.path.join(DL_ROOT, f"pl_{jid}")
        os.makedirs(dldir, exist_ok=True)
        job = {"id": jid, "dir": dldir, "state": "running", "total": 0, "done": 0,
               "current": "", "pct": 0, "failed": [], "error": "", "result": None,
               "filename": "", "label": label, "cancel": False, "created": time.time()}
        JOBS[jid] = job

    t = threading.Thread(target=run_job, daemon=True, args=(
        job, url, parse_indexes(indexes), int(quality), bool(numbering), bool(tags)))
    t.start()
    return JSONResponse(job_public(job))


def get_job(job_id):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "작업을 찾을 수 없습니다 (서버 재시작 또는 만료)")
    return job


@app.get("/api/playlist/status/{job_id}")
async def playlist_status(job_id: str):
    return JSONResponse(job_public(get_job(job_id)))


@app.post("/api/playlist/cancel/{job_id}")
async def playlist_cancel(job_id: str):
    job = get_job(job_id)
    if job["state"] == "running":
        job["cancel"] = True
    return JSONResponse(job_public(job))


@app.get("/api/playlist/result/{job_id}")
async def playlist_result(job_id: str):
    job = get_job(job_id)
    if job["state"] != "done" or not job["result"]:
        raise HTTPException(409, "아직 준비되지 않았습니다")
    if not os.path.isfile(job["result"]):
        raise HTTPException(410, "결과 파일이 정리되었습니다 (30분 경과). 다시 받아주세요")
    fname = job["filename"]
    # 헤더는 latin-1 만 허용 → filename= 엔 ASCII 대체, 실제 한글 이름은 filename*= 로
    ascii_name = re.sub(r'[^\x20-\x7e]', "_", fname).replace('"', "")
    disp = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(fname)}"
    media = "application/zip" if fname.endswith(".zip") else "audio/mpeg"
    return FileResponse(job["result"], media_type=media, headers={"Content-Disposition": disp})
