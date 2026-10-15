import io

from PIL import Image
import pytest


@pytest.mark.parametrize("path,media", [("/", "text/html"), ("/healthz", "application/json")])
def test_pages(client, path, media, assert_response):
    response = assert_response(client.get("/qr" + path), media=media)
    if path == "/healthz":
        assert response.json()["ok"] is True


@pytest.mark.parametrize("ecc", ["L", "M", "Q", "H"])
def test_generate_decode_roundtrip(client, ecc, assert_image, assert_response):
    text = f"just-this QR roundtrip {ecc} 한글"
    generated = client.post("/qr/api/generate", data={"text": text, "ecc": ecc,
                            "box": 10, "border": 4, "fg": "#000000", "bg": "#ffffff"})
    assert_image(generated)
    decoded = assert_response(client.post("/qr/api/read", files={
        "file": ("generated.png", generated.content, "image/png")}))
    assert decoded.json()["results"] == [text]


def test_read_generated_fixture(client, qr_bytes, assert_response):
    text, image = qr_bytes
    response = assert_response(client.post("/qr/api/read", files={"file": ("qr.png", image)}))
    assert response.json()["results"] == [text]


@pytest.mark.parametrize("payload", ["missing", "corrupt", "no_qr"])
def test_read_errors(client, image_bytes, payload, assert_response):
    files = None if payload == "missing" else {"file": ("image.png",
            b"broken" if payload == "corrupt" else image_bytes["png"])}
    assert_response(client.post("/qr/api/read", files=files), 422 if files is None else 400)


def test_generate_required_text(client, assert_response):
    assert_response(client.post("/qr/api/generate"), 422)


@pytest.mark.parametrize("box,border,expected_size", [(0, -1, 21), (99, 99, 2120), (2, 1, 46)])
def test_size_and_border_bounds(client, box, border, expected_size, assert_image):
    response = client.post("/qr/api/generate", data={"text": "A", "box": box, "border": border})
    assert_image(response, "PNG", (expected_size, expected_size))


def test_custom_colors_and_ecc_fallback(client, assert_image, assert_response):
    response = client.post("/qr/api/generate", data={"text": "color test", "ecc": "unknown",
        "box": 8, "border": 4, "fg": "#123", "bg": "#eef"})
    assert_image(response)
    with Image.open(io.BytesIO(response.content)) as image:
        pixels = image.convert("RGB").tobytes()
        assert set(zip(pixels[0::3], pixels[1::3], pixels[2::3])) == {(17, 34, 51), (238, 238, 255)}
    decoded = assert_response(client.post("/qr/api/read", files={"file": ("colors.png", response.content)}))
    assert decoded.json()["results"] == ["color test"]
