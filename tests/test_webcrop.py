import io
import math
import zipfile

import fitz
import numpy as np
from PIL import Image, ImageDraw
import pytest


PAPERS_MM = {"a3": (297, 420), "a4": (210, 297), "a5": (148, 210),
             "letter": (215.9, 279.4), "legal": (215.9, 355.6),
             "tabloid": (279.4, 431.8), "card": (90, 50), "card_us": (88.9, 50.8)}


@pytest.mark.parametrize("path,media", [("/", "text/html"), ("/healthz", "application/json")])
def test_pages(client, path, media, assert_response):
    response = assert_response(client.get("/webcrop" + path), media=media)
    if path == "/healthz":
        assert response.json() == {"ok": True}


@pytest.mark.parametrize("source", ["png", "jpg", "pdf"])
@pytest.mark.parametrize("deskew", [False, True])
@pytest.mark.parametrize("fmt", ["pdf", "png", "jpg"])
@pytest.mark.parametrize("lossless", [False, True])
def test_upload_preview_assemble(client, image_bytes, pdf_bytes, source, deskew,
                               fmt, lossless, assert_response, assert_image, assert_pdf):
    payload = pdf_bytes[3] if source == "pdf" else image_bytes[source]
    uploaded = assert_response(client.post("/webcrop/api/upload",
        files={"file": (f"input.{source}", payload)}, data={"auto_deskew": deskew})).json()
    assert uploaded["token"]
    assert len(uploaded["pages"]) == (3 if source == "pdf" else 1)
    files = []
    for index, page in enumerate(uploaded["pages"]):
        assert page["idx"] == index
        x, y, w, h = page["snap"]
        assert 0 <= x < x + w <= page["w"]
        assert 0 <= y < y + h <= page["h"]
        preview = assert_response(client.get("/webcrop/" + page["url"]), media="image/png")
        with Image.open(io.BytesIO(preview.content)) as image:
            assert image.format == "PNG"
            assert image.size == (page["w"], page["h"])
            # Emulate the browser's cropped-canvas upload, using actual preview pixels.
            image = image.crop((8, 8, 88, 56))
            stream = io.BytesIO()
            image.save(stream, "PNG")
        files.append(("files", (f"crop{index}.png", stream.getvalue(), "image/png")))
    response = client.post("/webcrop/api/assemble", files=files,
                           data={"fmt": fmt, "lossless": lossless, "quality": 75})
    if fmt == "pdf":
        assert_pdf(response, len(files))
        with fitz.open(stream=response.content, filetype="pdf") as document:
            assert document[0].rect.width == pytest.approx(80 * 72 / 200)
            assert document[0].rect.height == pytest.approx(48 * 72 / 200)
    elif len(files) == 1:
        assert_image(response, "JPEG" if fmt == "jpg" else "PNG", (80, 48))
    else:
        assert_response(response, media="application/zip")
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            assert archive.namelist() == [f"page_{i:03d}.{fmt}" for i in range(1, 4)]
            assert archive.testzip() is None
            for name in archive.namelist():
                with Image.open(io.BytesIO(archive.read(name))) as image:
                    assert image.format == ("JPEG" if fmt == "jpg" else "PNG")
                    assert image.size == (80, 48)
                    image.load()


@pytest.mark.parametrize("paper", PAPERS_MM)
@pytest.mark.parametrize("landscape", [False, True])
@pytest.mark.parametrize("mode", ["crop", "fit"])
@pytest.mark.parametrize("fmt", ["pdf", "png", "jpg"])
def test_paper_sizes(client, image_bytes, paper, landscape, mode, fmt,
                    assert_pdf, assert_image):
    response = client.post("/webcrop/api/assemble",
        files={"files": ("canvas.png", image_bytes["png"])},
        data={"fmt": fmt, "paper": paper, "paper_mode": mode, "landscape": landscape})
    width, height = PAPERS_MM[paper]
    if landscape:
        width, height = height, width
    if fmt == "pdf":
        assert_pdf(response, 1)
        with fitz.open(stream=response.content, filetype="pdf") as document:
            assert document[0].rect.width == pytest.approx(width * 72 / 25.4, abs=0.001)
            assert document[0].rect.height == pytest.approx(height * 72 / 25.4, abs=0.001)
    else:
        assert_image(response, "JPEG" if fmt == "jpg" else "PNG")
        with Image.open(io.BytesIO(response.content)) as image:
            assert abs(image.width - image.height * width / height) <= 2
            if mode == "crop":
                assert image.width <= 160 and image.height <= 96
                assert image.width == 160 or image.height == 96
            else:
                assert image.width >= 160 and image.height >= 96
                assert image.width == 160 or image.height == 96


@pytest.mark.parametrize("degrees", [-8, 8])
def test_deskew_corrects_tilt(client, degrees, assert_response):
    image = Image.new("RGB", (240, 160), "white")
    ImageDraw.Draw(image).rectangle((40, 72, 200, 88), fill="black")
    image = image.rotate(degrees, fillcolor="white")
    source = io.BytesIO()
    image.save(source, "PNG")

    def tilt(image):
        ys, xs = np.where(np.asarray(image.convert("L")) < 80)
        return abs(math.degrees(math.atan(np.polyfit(xs, ys, 1)[0])))

    before = tilt(image)
    upload = assert_response(client.post("/webcrop/api/upload",
        files={"file": ("tilted.png", source.getvalue())}, data={"auto_deskew": True})).json()
    preview = assert_response(client.get("/webcrop/" + upload["pages"][0]["url"]), media="image/png")
    with Image.open(io.BytesIO(preview.content)) as corrected:
        assert tilt(corrected) < before / 2, "deskew should reduce the measured line angle"


@pytest.mark.parametrize("path", ["missing/0", "missing/-1"])
def test_missing_preview(client, path, assert_response):
    assert_response(client.get("/webcrop/api/preview/" + path), 404)


def test_invalid_preview_index(client, image_bytes, assert_response):
    token = assert_response(client.post("/webcrop/api/upload",
        files={"file": ("input.png", image_bytes["png"])})).json()["token"]
    for index in (-1, 1):
        assert_response(client.get(f"/webcrop/api/preview/{token}/{index}"), 404)


@pytest.mark.parametrize("name,payload", [("bad.txt", b"text"), ("bad.png", b"broken")])
def test_bad_upload(client, name, payload, assert_response):
    assert_response(client.post("/webcrop/api/upload", files={"file": (name, payload)}), 400)


def test_bad_assemble(client, image_bytes, assert_response):
    assert_response(client.post("/webcrop/api/assemble", files={"files": ("bad.png", b"bad")}), 400)
    assert_response(client.post("/webcrop/api/assemble",
        files={"files": ("ok.png", image_bytes["png"])}, data={"paper": "unknown"}), 400)


@pytest.mark.parametrize("route", ["upload", "assemble"])
def test_missing_files(client, route, assert_response):
    assert_response(client.post("/webcrop/api/" + route), 422)
