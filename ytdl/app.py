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
import time
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
