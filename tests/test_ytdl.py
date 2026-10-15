import io
from pathlib import Path
import threading
import time
from urllib.parse import unquote
import zipfile

import httpx
import pytest

import ytdl.app as youtube_app


FORM_ROUTES = ["info", "download", "playlist/info", "playlist/start"]


@pytest.mark.parametrize("path,media", [("/", "text/html"), ("/healthz", "application/json")])
def test_pages(client, path, media, assert_response):
    response = assert_response(client.get("/ytdl" + path), media=media)
    if path == "/healthz":
        assert response.json()["ok"] is True
        assert response.json()["ffmpeg_dir"]
        assert response.json()["yt_dlp"]


@pytest.mark.parametrize("route", FORM_ROUTES)
@pytest.mark.parametrize("url", ["not-a-url", "file:///etc/passwd", "ftp://127.0.0.1/media.mp4"])
def test_url_validation(client, route, url, assert_response):
    assert_response(client.post("/ytdl/api/" + route, data={"url": url}), 400)


@pytest.mark.parametrize("route", FORM_ROUTES)
def test_missing_url(client, route, assert_response):
    assert_response(client.post("/ytdl/api/" + route), 422)


@pytest.mark.parametrize("route", ["info", "download", "playlist/info"])
def test_extractor_errors(client, route, failing_ytdlp, assert_response):
    response = assert_response(client.post("/ytdl/api/" + route,
        data={"url": "https://offline.invalid/example"}), 400)
    assert "offline" in response.json()["detail"]
    if route == "download":
        assert list(Path(youtube_app.DL_ROOT).iterdir()) == []


def test_empty_playlist(client, failing_ytdlp, monkeypatch, assert_response):
    monkeypatch.setattr(youtube_app.yt_dlp.YoutubeDL, "extract_info",
                        lambda *args, **kwargs: {"title": "Empty", "entries": []})
    assert_response(client.post("/ytdl/api/playlist/info",
        data={"url": "https://offline.invalid/empty"}), 400)


def test_download_without_output(client, failing_ytdlp, monkeypatch, assert_response):
    monkeypatch.setattr(youtube_app.yt_dlp.YoutubeDL, "download", lambda *args: None)
    assert_response(client.post("/ytdl/api/download",
        data={"url": "https://offline.invalid/empty"}), 400)


@pytest.mark.parametrize("quality", [0, 64, 256, 999])
def test_invalid_playlist_quality(client, quality, assert_response):
    assert_response(client.post("/ytdl/api/playlist/start",
        data={"url": "https://offline.invalid/list", "quality": quality}), 400)


@pytest.mark.parametrize("method,route", [("get", "status"), ("get", "result"), ("post", "cancel")])
def test_unknown_job(client, method, route, assert_response):
    assert_response(getattr(client, method)(f"/ytdl/api/playlist/{route}/missing"), 404)


@pytest.fixture
def seeded_job(tmp_path):
    """Seed otherwise timing-dependent error states, without a download worker."""
    def seed(state="running", name="testjob"):
        job = {"id": name, "state": state, "total": 2, "done": 0, "current": "",
               "pct": 0, "failed": [], "error": "", "filename": "", "result": None,
               "dir": str(tmp_path / name), "label": "", "cancel": False, "created": time.time()}
        youtube_app.JOBS[name] = job
        return job
    return seed


@pytest.mark.parametrize("state", ["running", "error", "canceled", "done"])
def test_result_not_ready(client, seeded_job, state, assert_response):
    seeded_job(state)
    assert_response(client.get("/ytdl/api/playlist/result/testjob"), 409)


def test_missing_result_file(client, seeded_job, tmp_path, assert_response):
    job = seeded_job("done")
    job.update(result=str(tmp_path / "removed.mp3"), filename="removed.mp3")
    assert_response(client.get("/ytdl/api/playlist/result/testjob"), 410)


def test_active_job_limit(client, seeded_job, assert_response):
    for i in range(youtube_app.MAX_ACTIVE_JOBS):
        seeded_job(name=f"busy{i}")
    assert_response(client.post("/ytdl/api/playlist/start",
        data={"url": "https://offline.invalid/list"}), 429)


def test_failed_job_lifecycle(client, failing_ytdlp, wait_for_job, assert_response):
    job = assert_response(client.post("/ytdl/api/playlist/start",
        data={"url": "https://offline.invalid/list"})).json()
    status = wait_for_job(job["id"])
    assert status["state"] == "error"
    assert "offline extractor failure" in status["error"]
    assert status["ready"] is False
    assert_response(client.get(f"/ytdl/api/playlist/result/{job['id']}"), 409)
    canceled = assert_response(client.post(f"/ytdl/api/playlist/cancel/{job['id']}")).json()
    assert canceled["state"] == "error"


def test_all_playlist_items_fail(client, failing_ytdlp, monkeypatch, wait_for_job, assert_response):
    monkeypatch.setattr(youtube_app, "flat_entries", lambda *args: ("List", [
        {"n": i, "title": f"Song {i}", "url": f"https://offline.invalid/{i}"}
        for i in (1, 2)], False))
    job = assert_response(client.post("/ytdl/api/playlist/start",
        data={"url": "https://offline.invalid/list", "tags": False})).json()
    status = wait_for_job(job["id"])
    assert status["state"] == "error"
    assert status["done"] == status["total"] == 2
    assert len(status["failed"]) == 2
    assert all("offline downloader failure" in item["reason"] for item in status["failed"])
    assert status["error"] and status["ready"] is False
    assert_response(client.get(f"/ytdl/api/playlist/result/{job['id']}"), 409)


def test_cancel_running_job(client, monkeypatch, wait_for_job, assert_response):
    entered, release = threading.Event(), threading.Event()

    def blocked_entries(*args):
        entered.set()
        assert release.wait(timeout=2), "Test did not release the extractor"
        return "List", [{"n": 1, "title": "Song", "url": "https://offline.invalid/song"}], False

    monkeypatch.setattr(youtube_app, "flat_entries", blocked_entries)
    job = assert_response(client.post("/ytdl/api/playlist/start",
        data={"url": "https://offline.invalid/list"})).json()
    try:
        assert entered.wait(timeout=1)
        assert_response(client.get(f"/ytdl/api/playlist/result/{job['id']}"), 409)
        canceled = assert_response(client.post(f"/ytdl/api/playlist/cancel/{job['id']}")).json()
        assert canceled["state"] == "running"
    finally:
        release.set()
    assert wait_for_job(job["id"])["state"] == "canceled"
    assert_response(client.get(f"/ytdl/api/playlist/result/{job['id']}"), 409)


def test_playlist_info_local(client, media_url, assert_response):
    info = assert_response(client.post("/ytdl/api/playlist/info",
        data={"url": media_url + "/list.html"})).json()
    assert info["title"] == "Fixture playlist"
    assert info["count"] == 2
    assert info["truncated"] is False
    assert [item["n"] for item in info["items"]] == [1, 2]
    assert all(item["title"] and item["url"].startswith(media_url) for item in info["items"])
    assert info["total_duration"] >= 0  # Generic HTML metadata may omit duration.


@pytest.mark.parametrize("page,title", [("single", "Fixture video"), ("korean", "한글 제목 테스트")])
def test_info_local(client, media_url, page, title, assert_response):
    info = assert_response(client.post("/ytdl/api/info", data={"url": f"{media_url}/{page}.html"})).json()
    # Generic HTML extraction may append a media-entry ordinal, even for one tag.
    assert info["title"] in (title, f"{title} (1)")
    assert isinstance(info["heights"], list)
    assert {"duration", "thumbnail", "uploader"} <= info.keys()


@pytest.mark.parametrize("quality,numbering,tags", [(128, True, False), (192, False, True), (320, True, True)])
def test_playlist_local_zip(client, media_url, quality, numbering, tags,
                            wait_for_job, assert_response, assert_media):
    job = assert_response(client.post("/ytdl/api/playlist/start", data={
        "url": media_url + "/list.html", "quality": quality, "numbering": numbering,
        "tags": tags, "label": "한글 제목 테스트",
    })).json()
    status = wait_for_job(job["id"])
    assert status["state"] == "done", status
    assert status["done"] == status["total"] == 2
    assert status["failed"] == [] and status["error"] == ""
    assert status["ready"] is True
    result = assert_response(client.get(f"/ytdl/api/playlist/result/{job['id']}"), media="application/zip")
    disposition = result.headers["content-disposition"]
    disposition.encode("ascii")
    assert "filename=" in disposition and "filename*=UTF-8''" in disposition
    assert "한글 제목 테스트.zip" in unquote(disposition)
    with zipfile.ZipFile(io.BytesIO(result.content)) as archive:
        assert len(archive.namelist()) == 2
        assert len(set(archive.namelist())) == 2
        assert archive.testzip() is None
        for index, name in enumerate(archive.namelist(), 1):
            assert name.endswith(".mp3")
            assert name.startswith(f"{index:02d} - ") is numbering
            # The same decoder checks apply to zip members as direct responses.
            member = httpx.Response(200, content=archive.read(name), headers={
                "content-type": "audio/mpeg", "content-disposition": "attachment"})
            assert_media(member, "mp3", audio=True, duration=(1.9, 2.2))
    assert assert_response(client.post(f"/ytdl/api/playlist/cancel/{job['id']}")).json()["state"] == "done"


def test_playlist_selected_korean_single(client, media_url, wait_for_job, assert_response, assert_media):
    job = assert_response(client.post("/ytdl/api/playlist/start", data={
        "url": media_url + "/korean.html", "indexes": "1", "tags": False,
        "numbering": False, "quality": 128,
    })).json()
    status = wait_for_job(job["id"])
    assert status["state"] == "done", status
    assert status["done"] == status["total"] == 1
    result = client.get(f"/ytdl/api/playlist/result/{job['id']}")
    assert_media(result, "mp3", audio=True, duration=(1.9, 2.2))
    result.headers["content-disposition"].encode("ascii")
    assert "한글 제목 테스트" in unquote(result.headers["content-disposition"])


def test_playlist_selection_empty(client, media_url, wait_for_job, assert_response):
    job = assert_response(client.post("/ytdl/api/playlist/start", data={
        "url": media_url + "/list.html", "indexes": "99",
    })).json()
    status = wait_for_job(job["id"])
    assert status["state"] == "error"
    assert status["error"]
    assert_response(client.get(f"/ytdl/api/playlist/result/{job['id']}"), 409)


@pytest.mark.parametrize("page", ["single", "korean"])
@pytest.mark.parametrize("mode", ["audio", "video"])
@pytest.mark.parametrize("trim", [False, True])
def test_download_local(client, media_url, page, mode, trim, assert_media):
    options = {"url": f"{media_url}/{page}.html", "mode": mode, "height": 96,
               "subs": mode == "video"}
    if trim:
        options.update(start=0.25, end=1.25)
    response = client.post("/ytdl/api/download", data=options)
    assert_media(response, "mp3" if mode == "audio" else "mp4", audio=True,
                 size=None if mode == "audio" else (160, 96),
                 duration=(0.85, 1.25) if trim else (1.9, 2.2))
    disposition = response.headers["content-disposition"]
    disposition.encode("ascii")
    assert "filename=" in disposition and "filename*=UTF-8''" in disposition
    assert unquote(disposition.split("filename*=UTF-8''", 1)[1]).endswith(
        ".mp3" if mode == "audio" else ".mp4")
