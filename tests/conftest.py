"""Generated fixtures and HTTP-only smoke tests against the mounted hub."""
import io
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import socket
import subprocess
import sys
import threading
import time
from collections import Counter, defaultdict

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

import fitz
import imageio_ffmpeg
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
import qrcode

from hub.app import app
import vidconv.app as video_app
import webcrop.app as crop_app
import ytdl.app as youtube_app


@pytest.fixture
def allowed_http_endpoints():
    return set()


@pytest.fixture(autouse=True)
def isolate_runtime(monkeypatch, tmp_path, allowed_http_endpoints):
    """Only test-owned session files/jobs; prevent accidental offline-test egress."""
    for module, attribute in ((crop_app, "TMP_ROOT"), (video_app, "TMP_ROOT"),
                              (youtube_app, "DL_ROOT")):
        directory = tmp_path / module.__name__.split(".")[0]
        directory.mkdir()
        monkeypatch.setattr(module, attribute, str(directory))
    monkeypatch.setattr(crop_app, "SESSIONS", {})
    monkeypatch.setattr(video_app, "SESSIONS", {})
    monkeypatch.setattr(youtube_app, "JOBS", {})
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def guarded(original):
        def connect(sock, address):
            assert address in allowed_http_endpoints, (
                f"Offline test attempted a connection outside its fixture server: {address}"
            )
            return original(sock, address)
        return connect

    monkeypatch.setattr(socket.socket, "connect", guarded(original_connect))
    monkeypatch.setattr(socket.socket, "connect_ex", guarded(original_connect_ex))

    # Join every playlist worker before monkeypatch restores real app state/paths.
    workers = []
    original_run_job = youtube_app.run_job

    def tracked_run_job(*args):
        workers.append(threading.current_thread())
        return original_run_job(*args)

    monkeypatch.setattr(youtube_app, "run_job", tracked_run_job)
    yield
    for job in youtube_app.JOBS.values():
        job["cancel"] = True
    for worker in workers:
        worker.join(timeout=3)
        assert not worker.is_alive(), "Playlist worker outlived its test"


@pytest.fixture
def client():
    # Expose unhandled application errors as HTTP 500 for useful status assertions.
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def image_bytes():
    result = {}
    image = Image.new("RGB", (160, 96), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((16, 12, 140, 80), fill=(30, 90, 170))
    draw.line((0, 0, 159, 95), fill="red", width=3)
    for extension, fmt in (("png", "PNG"), ("jpg", "JPEG")):
        stream = io.BytesIO()
        image.save(stream, fmt)
        result[extension] = stream.getvalue()
    transparent = Image.new("RGBA", image.size, (255, 0, 0, 0))
    stream = io.BytesIO()
    transparent.save(stream, "PNG")
    result["transparent"] = stream.getvalue()
    return result


@pytest.fixture(scope="session")
def pdf_bytes():
    documents = {}
    for count in (1, 3):
        with fitz.open() as document:
            for page_number in range(1, count + 1):
                page = document.new_page(width=240, height=320)
                page.insert_text((24, 40), f"Smoke page {page_number}")
                page.draw_rect(fitz.Rect(24, 64, 200, 260), color=(0, 0, 1))
            documents[count] = document.tobytes()
    return documents


@pytest.fixture(scope="session")
def ffmpeg():
    return imageio_ffmpeg.get_ffmpeg_exe()


@pytest.fixture(scope="session")
def video_bytes(tmp_path_factory, ffmpeg):
    path = tmp_path_factory.mktemp("video-fixture") / "two-seconds.mp4"
    command = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
               "-f", "lavfi", "-i", "testsrc=size=160x96:rate=12",
               "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
               "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p",
               "-threads", "1", "-c:a", "aac", "-shortest", str(path)]
    result = subprocess.run(command, capture_output=True, timeout=5)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    return path.read_bytes()


@pytest.fixture(scope="session")
def media_http_server(tmp_path_factory, video_bytes, image_bytes):
    """Real generic-extractor pages; no Internet, external sites or fixed ports."""
    root = tmp_path_factory.mktemp("ytdlp-http")
    for number in (1, 2):
        (root / f"song{number}.mp4").write_bytes(video_bytes)
    (root / "cover.jpg").write_bytes(image_bytes["jpg"])
    for name, title, count in (("list", "Fixture playlist", 2),
                               ("single", "Fixture video", 1),
                               ("korean", "한글 제목 테스트", 1)):
        videos = "".join(f'<video src="song{i}.mp4" poster="cover.jpg"></video>'
                         for i in range(1, count + 1))
        (root / f"{name}.html").write_text(
            f'<!doctype html><html><head><meta charset="utf-8"><title>{title}</title>'
            f'</head><body>{videos}</body></html>', encoding="utf-8")

    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(root)))
    worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02},
                              daemon=True)
    worker.start()
    try:
        yield server.server_address
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
        assert not worker.is_alive()


@pytest.fixture
def media_url(media_http_server, allowed_http_endpoints):
    allowed_http_endpoints.add(media_http_server)
    host, port = media_http_server
    return f"http://{host}:{port}"


@pytest.fixture
def assert_media(ffmpeg, tmp_path, assert_response):
    def check(response, fmt, size=None, audio=None, duration=None):
        mime = {"mp4": "video/mp4", "webm": "video/webm", "mp3": "audio/mpeg"}[fmt]
        assert_response(response, media=mime)
        assert "attachment" in response.headers.get("content-disposition", "")
        path = tmp_path / f"verify.{fmt}"
        path.write_bytes(response.content)
        # Decode all streams, rather than merely trusting a file extension/header.
        result = subprocess.run([ffmpeg, "-hide_banner", "-i", str(path), "-f", "null", "-"],
                                capture_output=True, text=True, timeout=4)
        assert result.returncode == 0, result.stderr
        metadata = result.stderr.split("Output #", 1)[0]
        if size:
            assert re.search(rf"Video:.*\b{size[0]}x{size[1]}\b", metadata), metadata
        if audio is not None:
            assert ("Audio:" in metadata) is audio, metadata
        if duration:
            match = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", metadata)
            assert match, metadata
            seconds = int(match[1]) * 3600 + int(match[2]) * 60 + float(match[3])
            assert duration[0] <= seconds <= duration[1], metadata
        return response
    return check


@pytest.fixture
def wait_for_job(client, assert_response):
    def wait(job_id, timeout=6):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = assert_response(client.get(f"/ytdl/api/playlist/status/{job_id}")).json()
            assert 0 <= state["done"] <= state["total"]
            assert 0 <= state["pct"] <= 100
            assert not ({"dir", "result", "cancel", "created"} & state.keys())
            if state["state"] != "running":
                return state
            time.sleep(0.02)
        pytest.fail(f"Playlist did not finish within {timeout}s: {state}")
    return wait


@pytest.fixture(scope="session")
def qr_bytes():
    text = "just-this smoke QR 123"
    stream = io.BytesIO()
    qrcode.make(text, box_size=8, border=4).save(stream, format="PNG")
    return text, stream.getvalue()


@pytest.fixture
def assert_response():
    def check(response, status=200, media="application/json"):
        assert response.status_code == status, response.text[:800]
        assert response.headers["content-type"].split(";")[0] == media
        if status >= 400:
            assert response.json()["detail"]
        return response
    return check


@pytest.fixture
def assert_image(assert_response):
    def check(response, fmt="PNG", size=None):
        mime = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp",
                "GIF": "image/gif"}[fmt]
        assert_response(response, media=mime)
        assert "attachment" in response.headers.get("content-disposition", "")
        with Image.open(io.BytesIO(response.content)) as image:
            assert image.format == fmt
            image.load()
            assert image.width > 0 and image.height > 0
            if size:
                assert image.size == size
        return response
    return check


@pytest.fixture
def assert_pdf(assert_response):
    def check(response, pages):
        assert_response(response, media="application/pdf")
        assert "attachment" in response.headers.get("content-disposition", "")
        with fitz.open(stream=response.content, filetype="pdf") as document:
            assert document.page_count == pages
            for page in document:
                assert page.get_pixmap().width > 0
        return response
    return check


@pytest.fixture
def failing_ytdlp(monkeypatch):
    """Deterministic extractor boundary failure, never a real network test."""
    class FailingYoutubeDL:
        def __init__(self, options):
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, *args, **kwargs):
            raise RuntimeError("offline extractor failure")

        def download(self, *args, **kwargs):
            raise RuntimeError("offline downloader failure")

    monkeypatch.setattr(youtube_app.yt_dlp, "YoutubeDL", FailingYoutubeDL)


def pytest_terminal_summary(terminalreporter):
    """Always finish with a per-tool table, including setup/teardown failures."""
    counts = defaultdict(Counter)
    for outcome in ("passed", "failed", "error", "skipped"):
        for report in terminalreporter.stats.get(outcome, []):
            name = Path(report.nodeid.split("::", 1)[0]).stem.removeprefix("test_")
            counts[name][outcome] += 1
    terminalreporter.write_sep("=", "Per-tool smoke results")
    terminalreporter.write_line("tool       pass  fail  skip")
    for tool, results in sorted(counts.items()):
        terminalreporter.write_line(
            f"{tool:<10} {results['passed']:>4}  "
            f"{results['failed'] + results['error']:>4}  {results['skipped']:>4}"
        )
