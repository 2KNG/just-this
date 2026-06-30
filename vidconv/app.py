#!/usr/bin/env python3
"""
vidconv — 동영상 자르기(crop·trim)·변환 웹앱.

  1) 업로드: 동영상 → 서버가 길이/해상도 분석 + 대표 프레임 추출
  2) 편집  : 프레임 위에서 영역 crop(Cropper.js), 구간 trim(시작~끝), 리사이즈
  3) 변환  : ffmpeg 로 MP4 / WEBM / GIF / MP3(오디오만) / PNG(프레임) 출력

ffmpeg 는 시스템에 있으면 그걸 쓰고, 없으면 pip 의 imageio-ffmpeg 정적 빌드를 쓴다.
단일 프로세스로 실행. 세션은 임시폴더, 30분 TTL.
"""

import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

HERE = os.path.dirname(os.path.abspath(__file__))
TMP_ROOT = os.path.join(tempfile.gettempdir(), "vidconv_sessions")
os.makedirs(TMP_ROOT, exist_ok=True)
MAX_UPLOAD_MB = 500
SESSION_TTL_SEC = 60 * 30

SESSIONS = {}  # token -> {"dir", "src", "ts", "dur", "w", "h"}

app = FastAPI(title="vidconv")


def ffmpeg_exe():
    p = shutil.which("ffmpeg")
    if p:
        return p
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


FFMPEG = ffmpeg_exe()


def probe(path):
    """ffmpeg -i 출력에서 길이/해상도 파싱 (ffprobe 없이도 동작)."""
    out = subprocess.run([FFMPEG, "-hide_banner", "-i", path],
                         capture_output=True, text=True).stderr
    dur, w, h = 0.0, 0, 0
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", out)
    if m:
        dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    m = re.search(r"Video:.*?[,\s](\d{2,5})x(\d{2,5})", out)
    if m:
        w, h = int(m.group(1)), int(m.group(2))
    return dur, w, h


def run_ff(args):
    r = subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", *args],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise HTTPException(400, "ffmpeg 실패: " + (r.stderr.strip()[-400:] or "unknown"))


def cleanup():
    now = time.time()
    for tk in list(SESSIONS):
        if now - SESSIONS[tk]["ts"] > SESSION_TTL_SEC:
            shutil.rmtree(SESSIONS[tk]["dir"], ignore_errors=True)
            SESSIONS.pop(tk, None)


def get_session(token):
    s = SESSIONS.get(token)
    if not s:
        raise HTTPException(404, "세션 만료/없음. 다시 올려주세요.")
    return s


@app.get("/", response_class=HTMLResponse)
def index():
    with open(os.path.join(HERE, "static", "index.html"), encoding="utf-8") as f:
        return f.read()


@app.get("/healthz")
def healthz():
    return {"ok": True, "ffmpeg": FFMPEG}


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    cleanup()
    data = await file.read()
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"파일이 너무 큼 (최대 {MAX_UPLOAD_MB}MB)")
    token = uuid.uuid4().hex
    sdir = os.path.join(TMP_ROOT, token)
    os.makedirs(sdir, exist_ok=True)
    ext = os.path.splitext(file.filename or "")[1].lower() or ".mp4"
    src = os.path.join(sdir, "src" + ext)
    with open(src, "wb") as f:
        f.write(data)

    dur, w, h = probe(src)
    if w == 0:
        shutil.rmtree(sdir, ignore_errors=True)
        raise HTTPException(400, "동영상을 읽을 수 없음 (지원 안 되는 형식일 수 있음)")

    # 대표 프레임 (가운데) 추출 — 원본 해상도, crop 좌표 기준
    frame = os.path.join(sdir, "frame.jpg")
    run_ff(["-ss", str(max(0, dur / 2)), "-i", src, "-frames:v", "1", "-q:v", "3", frame])

    SESSIONS[token] = {"dir": sdir, "src": src, "ts": time.time(), "dur": dur, "w": w, "h": h}
    return {"token": token, "dur": round(dur, 3), "w": w, "h": h, "frame_url": f"api/frame/{token}"}


@app.get("/api/frame/{token}")
def frame(token: str):
    s = get_session(token)
    return FileResponse(os.path.join(s["dir"], "frame.jpg"), media_type="image/jpeg",
                        headers={"Cache-Control": "no-store"})


CRF = {"high": 18, "medium": 23, "small": 28}


@app.post("/api/convert")
async def convert(
    token: str = Form(...),
    fmt: str = Form("mp4"),            # mp4 | webm | gif | mp3 | png
    start: float = Form(0.0),
    end: float = Form(0.0),           # 0 이면 끝까지
    crop: str = Form(""),             # "x,y,w,h" (원본 픽셀) 또는 빈값
    scale_w: int = Form(0),           # 가로 px, 0이면 원본
    fps: int = Form(12),              # gif 용
    mute: bool = Form(False),
    quality: str = Form("medium"),    # high | medium | small
):
    s = get_session(token)
    s["ts"] = time.time()
    src, sdir = s["src"], s["dir"]
    dur = s["dur"]

    start = max(0.0, min(start, dur))
    end = dur if end <= 0 else min(end, dur)
    if end <= start:
        end = dur
    seg = max(0.05, end - start)

    # 비디오 필터 체인 (crop → scale)
    vf = []
    if crop:
        try:
            cx, cy, cw, ch = (int(round(float(v))) for v in crop.split(","))
            cw, ch = max(2, cw - cw % 2), max(2, ch - ch % 2)
            vf.append(f"crop={cw}:{ch}:{max(0, cx)}:{max(0, cy)}")
        except ValueError:
            raise HTTPException(400, "crop 형식 오류")
    if scale_w and scale_w > 0:
        vf.append(f"scale={int(scale_w)}:-2:flags=lanczos")

    crf = CRF.get(quality, 23)
    out = os.path.join(sdir, "out." + ("jpg" if fmt == "png" else fmt))
    base = []
    if start > 0:
        base += ["-ss", f"{start:.3f}"]
    base += ["-i", src, "-t", f"{seg:.3f}"]

    if fmt == "mp4":
        args = base + (["-vf", ",".join(vf)] if vf else []) + [
            "-c:v", "libx264", "-crf", str(crf), "-preset", "veryfast", "-pix_fmt", "yuv420p"]
        args += ["-an"] if mute else ["-c:a", "aac", "-b:a", "160k"]
        args += [out]
    elif fmt == "webm":
        args = base + (["-vf", ",".join(vf)] if vf else []) + [
            "-c:v", "libvpx-vp9", "-crf", str(crf + 8), "-b:v", "0", "-row-mt", "1"]
        args += ["-an"] if mute else ["-c:a", "libopus", "-b:a", "128k"]
        args += [out]
    elif fmt == "gif":
        chain = vf + [f"fps={max(1, min(30, int(fps)))}"]
        graph = "[0:v]" + (",".join(chain) + "," if chain else "") + \
            "split[s0][s1];[s0]palettegen=stats_mode=diff[p];[s1][p]paletteuse=dither=bayer:bayer_scale=3"
        args = base + ["-filter_complex", graph, "-loop", "0", out]
    elif fmt == "mp3":
        args = base + ["-vn", "-c:a", "libmp3lame", "-q:a", "2", out]
    elif fmt == "png":
        out = os.path.join(sdir, "out.png")
        args = base[:-2] + ["-frames:v", "1"] + (["-vf", ",".join(vf)] if vf else []) + [out]
        # png: -t 빼고 한 프레임만
    else:
        raise HTTPException(400, f"알 수 없는 형식: {fmt}")

    run_ff(args)
    media = {"mp4": "video/mp4", "webm": "video/webm", "gif": "image/gif",
             "mp3": "audio/mpeg", "png": "image/png"}[fmt]
    ext = "png" if fmt == "png" else fmt
    return FileResponse(out, media_type=media,
                        headers={"Content-Disposition": f'attachment; filename="vidconv.{ext}"'})
