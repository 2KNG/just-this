import io
import json
import zipfile

from PIL import Image
import pytest


@pytest.mark.parametrize("path,media", [("/", "text/html"), ("/healthz", "application/json")])
def test_pages(client, path, media, assert_response):
    response = assert_response(client.get("/imgconv" + path), media=media)
    if path == "/healthz":
        assert response.json()["ok"] is True
        assert isinstance(response.json()["heif"], bool)


@pytest.mark.parametrize("source", ["png", "jpg"])
@pytest.mark.parametrize("fmt,pil_format", [("png", "PNG"), ("jpg", "JPEG"), ("webp", "WEBP"), ("keep", None)])
def test_convert_formats(client, image_bytes, source, fmt, pil_format, assert_image):
    response = client.post("/imgconv/api/convert",
                           files={"files": (f"input.{source}", image_bytes[source])},
                           data={"options": json.dumps({"fmt": fmt, "quality": 85,
                                                        "webp_lossless": fmt == "webp"})})
    assert_image(response, pil_format or {"png": "PNG", "jpg": "JPEG"}[source], (160, 96))


@pytest.mark.parametrize("mode,value,size", [
    ("none", 0, (80, 40)), ("width", 40, (40, 20)), ("height", 20, (40, 20)),
    ("longest", 40, (40, 20)), ("percent", 50, (40, 20)),
])
def test_crop_and_resize(client, image_bytes, mode, value, size, assert_image):
    response = client.post("/imgconv/api/convert", files={"files": ("crop.png", image_bytes["png"])},
                           data={"options": json.dumps({"fmt": "png", "crop": [10, 10, 80, 40],
                                                        "resize_mode": mode, "resize_value": value})})
    assert_image(response, size=size)


def test_transparency_background(client, image_bytes, assert_image):
    response = client.post("/imgconv/api/convert",
                           files={"files": ("alpha.png", image_bytes["transparent"])},
                           data={"options": json.dumps({"fmt": "jpg", "bg": "#00ff00"})})
    assert_image(response, "JPEG")
    with Image.open(io.BytesIO(response.content)) as image:
        r, g, b = image.getpixel((80, 48))
        assert r < 5 and g > 250 and b < 5


@pytest.mark.parametrize("strip", [True, False])
def test_exif_option(client, strip, assert_image):
    image = Image.new("RGB", (24, 16), "blue")
    exif = Image.Exif()
    exif[270] = "smoke metadata"
    source = io.BytesIO()
    image.save(source, "JPEG", exif=exif)
    response = client.post("/imgconv/api/convert", files={"files": ("meta.jpg", source.getvalue())},
                           data={"options": json.dumps({"fmt": "jpg", "strip_meta": strip})})
    assert_image(response, "JPEG")
    with Image.open(io.BytesIO(response.content)) as output:
        assert output.getexif().get(270) == (None if strip else "smoke metadata")


def test_batch_zip_and_skip(client, image_bytes, assert_response):
    response = client.post("/imgconv/api/convert", files=[
        ("files", ("한글.png", image_bytes["png"])),
        ("files", ("한글.jpg", image_bytes["jpg"])),
        ("files", ("bad.txt", b"not an image")),
    ], data={"options": '{"fmt":"png"}'})
    assert_response(response, media="application/zip")
    assert response.headers["x-skipped"]
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.namelist() == ["한글.png", "한글_1.png"]
        assert archive.testzip() is None
        for name in archive.namelist():
            with Image.open(io.BytesIO(archive.read(name))) as image:
                assert image.size == (160, 96)
                image.load()


@pytest.mark.parametrize("options,payload,status", [
    ("{", b"bad", 400), ("{}", b"bad", 400),
])
def test_invalid_input(client, options, payload, status, assert_response):
    assert_response(client.post("/imgconv/api/convert", files={"files": ("bad.png", payload)},
                                data={"options": options}), status)


def test_missing_upload(client, assert_response):
    assert_response(client.post("/imgconv/api/convert"), 422)


@pytest.mark.parametrize("lossless", [False, True])
def test_webp_lossy_and_lossless(client, image_bytes, lossless, assert_image):
    response = client.post("/imgconv/api/convert", files={"files": ("input.png", image_bytes["png"])},
        data={"options": json.dumps({"fmt": "webp", "webp_lossless": lossless, "quality": 60})})
    assert_image(response, "WEBP", (160, 96))
    if lossless:
        with Image.open(io.BytesIO(image_bytes["png"])) as original, \
                Image.open(io.BytesIO(response.content)) as converted:
            assert converted.convert("RGB").tobytes() == original.convert("RGB").tobytes()


@pytest.mark.parametrize("source", ["WEBP", "BMP", "TIFF", "GIF"])
def test_keep_source_format_or_png_fallback(client, source, assert_image):
    stream = io.BytesIO()
    Image.new("RGB", (24, 16), "blue").save(stream, source)
    response = client.post("/imgconv/api/convert",
        files={"files": ("input." + source.lower(), stream.getvalue())},
        data={"options": '{"fmt":"keep"}'})
    assert_image(response, "WEBP" if source == "WEBP" else "PNG", (24, 16))


def test_exif_orientation_applied(client, assert_image):
    stream = io.BytesIO()
    exif = Image.Exif()
    exif[274] = 6  # 90 degrees clockwise
    Image.new("RGB", (24, 16), "blue").save(stream, "JPEG", exif=exif)
    response = client.post("/imgconv/api/convert",
        files={"files": ("rotated.jpg", stream.getvalue())}, data={"options": '{"fmt":"png"}'})
    assert_image(response, "PNG", (16, 24))


def test_single_korean_filename_header(client, image_bytes, assert_image):
    response = client.post("/imgconv/api/convert", files={"files": ("한글.png", image_bytes["png"])})
    assert_image(response, "PNG")
    response.headers["content-disposition"].encode("ascii")
    assert "filename*=UTF-8''" in response.headers["content-disposition"]
