#!/usr/bin/env python3
"""
가짜 재생목록 만들기 — 유튜브 없이 ytdl 재생목록 탭을 돌려보기 위한 로컬 재료.

yt-dlp 는 <video> 태그가 여러 개 있는 HTML 페이지를 '재생목록'으로 인식한다(generic 추출기).
그래서 짧은 mp4 3개 + 표지 이미지 + list.html 을 만들어 localhost 로 서빙하면
목록 훑기 → 곡별 다운로드 → mp3 변환(320k) → 태그·앨범아트 → zip 까지 실제 파이프라인이 다 돈다.
(한 곡 3초라 작업이 2초면 끝남 → UI 반복 작업에 딱 좋다)

    . venv/bin/activate
    python ytdl/devtest/make_fake_playlist.py            # ytdl/devtest/_fake/ 에 생성
    python ytdl/devtest/make_fake_playlist.py --serve    # 생성 + http://127.0.0.1:8811 서빙

그 다음 재생목록 탭에 http://127.0.0.1:8811/list.html 붙여넣기.
"""

import argparse
import http.server
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "_fake")   # .gitignore 됨


def ffmpeg_exe():
    import shutil
    return shutil.which("ffmpeg") or __import__("imageio_ffmpeg").get_ffmpeg_exe()


def build(n=3, seconds=3):
    os.makedirs(OUT, exist_ok=True)
    ff = ffmpeg_exe()
    for i in range(1, n + 1):
        subprocess.run([ff, "-y", "-loglevel", "error",
                        "-f", "lavfi", "-i", f"sine=frequency={300 * i}:duration={seconds}",
                        "-f", "lavfi", "-i", f"color=c=blue:s=320x240:d={seconds}",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                        os.path.join(OUT, f"song{i}.mp4")], check=True)
    subprocess.run([ff, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=orange:s=300x300:d=1",
                    "-frames:v", "1", os.path.join(OUT, "cover.jpg")], check=True)
    vids = "\n".join(f'<video src="song{i}.mp4" poster="cover.jpg"></video>' for i in range(1, n + 1))
    with open(os.path.join(OUT, "list.html"), "w", encoding="utf-8") as f:
        f.write(f"<html><head><title>테스트 재생목록</title></head><body>\n{vids}\n</body></html>\n")
    with open(os.path.join(OUT, "single.html"), "w", encoding="utf-8") as f:   # 앨범아트 임베드 확인용(1곡+poster)
        f.write('<html><head><title>표지 있는 곡</title></head><body>\n<video src="song1.mp4" poster="cover.jpg"></video>\n</body></html>\n')
    print(f"생성: {OUT} (song1..{n}.mp4, cover.jpg, list.html, single.html)")


def serve(port):
    os.chdir(OUT)
    print(f"서빙: http://127.0.0.1:{port}/list.html  (Ctrl+C 로 종료)")
    http.server.ThreadingHTTPServer(("127.0.0.1", port), http.server.SimpleHTTPRequestHandler).serve_forever()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--serve", action="store_true", help="생성 후 localhost 로 서빙")
    ap.add_argument("--port", type=int, default=8811)
    ap.add_argument("--n", type=int, default=3, help="곡 수")
    a = ap.parse_args()
    build(a.n)
    if a.serve:
        try:
            serve(a.port)
        except KeyboardInterrupt:
            sys.exit(0)
