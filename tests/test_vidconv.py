import io

from PIL import Image
import pytest


@pytest.fixture
def uploaded_video(client, video_bytes, assert_response):
    body = assert_response(client.post("/vidconv/api/upload",
        files={"file": ("fixture.mp4", video_bytes, "video/mp4")})).json()
    assert body["w"] == 160 and body["h"] == 96
    assert body["dur"] == pytest.approx(2, abs=0.1)
    assert body["token"]
    return body


@pytest.mark.parametrize("path,media", [("/", "text/html"), ("/healthz", "application/json")])
def test_pages(client, path, media, assert_response):
    response = assert_response(client.get("/vidconv" + path), media=media)
    if path == "/healthz":
        assert response.json()["ok"] is True
        assert response.json()["ffmpeg"]


def test_upload_and_frame(client, uploaded_video, assert_response):
    response = assert_response(client.get("/vidconv/" + uploaded_video["frame_url"]),
                               media="image/jpeg")
    assert response.headers["cache-control"] == "no-store"
    with Image.open(io.BytesIO(response.content)) as image:
        assert image.format == "JPEG" and image.size == (160, 96)
        image.load()


@pytest.mark.parametrize("fmt", ["mp4", "webm"])
@pytest.mark.parametrize("quality", ["high", "medium", "small"])
@pytest.mark.parametrize("mute", [False, True])
def test_video_trim_crop_resize(client, uploaded_video, fmt, quality, mute, assert_media):
    response = client.post("/vidconv/api/convert", data={
        "token": uploaded_video["token"], "fmt": fmt, "quality": quality, "mute": mute,
        "start": 0.25, "end": 1.25, "crop": "10,8,120,72", "scale_w": 80,
    })
    assert_media(response, fmt, size=(80, 48), audio=not mute, duration=(0.9, 1.2))


@pytest.mark.parametrize("fmt", ["gif", "mp3", "png"])
def test_other_formats_with_edits(client, uploaded_video, fmt, assert_image, assert_media):
    response = client.post("/vidconv/api/convert", data={
        "token": uploaded_video["token"], "fmt": fmt, "start": 0.25, "end": 1.25,
        "crop": "10,8,120,72", "scale_w": 80, "fps": 5,
    })
    if fmt == "mp3":
        assert_media(response, fmt, audio=True, duration=(0.9, 1.2))
    else:
        assert_image(response, "GIF" if fmt == "gif" else "PNG", (80, 48))
        if fmt == "gif":
            with Image.open(io.BytesIO(response.content)) as image:
                assert image.n_frames >= 2
                assert image.info["loop"] == 0
                milliseconds = 0
                for i in range(image.n_frames):
                    image.seek(i)
                    image.load()
                    milliseconds += image.info["duration"]
                assert 800 <= milliseconds <= 1200


@pytest.mark.parametrize("start,end,bounds", [
    (-1, 0, (1.9, 2.2)), (0.5, 99, (1.4, 1.7)), (0.5, 0.1, (1.4, 1.7)),
])
def test_trim_bounds_without_spatial_edits(client, uploaded_video, start, end, bounds, assert_media):
    response = client.post("/vidconv/api/convert", data={
        "token": uploaded_video["token"], "fmt": "mp4", "start": start, "end": end,
    })
    assert_media(response, "mp4", size=(160, 96), audio=True, duration=bounds)


@pytest.mark.parametrize("options", [{"fmt": "unknown"}, {"crop": "bad"},
    {"crop": "0,0,1"}, {"crop": "0,0,500,500"}])
def test_invalid_conversion(client, uploaded_video, options, assert_response):
    assert_response(client.post("/vidconv/api/convert",
        data={"token": uploaded_video["token"], **options}), 400)


def test_bad_upload(client, assert_response):
    assert_response(client.post("/vidconv/api/upload", files={"file": ("bad.mp4", b"bad")}), 400)


def test_missing_session(client, assert_response):
    assert_response(client.get("/vidconv/api/frame/missing"), 404)
    assert_response(client.post("/vidconv/api/convert", data={"token": "missing"}), 404)


@pytest.mark.parametrize("route", ["upload", "convert"])
def test_missing_fields(client, route, assert_response):
    assert_response(client.post("/vidconv/api/" + route), 422)
