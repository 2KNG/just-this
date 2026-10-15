import io
import zipfile

import fitz
from PIL import Image
import pytest


@pytest.mark.parametrize("path,media", [("/", "text/html"), ("/healthz", "application/json")])
def test_pages(client, path, media, assert_response):
    response = assert_response(client.get("/pdftools" + path), media=media)
    if path == "/healthz":
        assert response.json() == {"ok": True}


def test_merge_mixed_sources_in_order(client, pdf_bytes, image_bytes, assert_pdf):
    response = client.post("/pdftools/api/merge", files=[
        ("files", ("first.pdf", pdf_bytes[1])),
        ("files", ("second.png", image_bytes["png"])),
        ("files", ("third.pdf", pdf_bytes[3])),
        ("files", ("fourth.jpg", image_bytes["jpg"])),
    ])
    assert_pdf(response, 6)
    with fitz.open(stream=response.content, filetype="pdf") as document:
        assert "Smoke page 1" in document[0].get_text()
        assert document[1].get_images()
        assert "Smoke page 3" in document[4].get_text()
        assert document[5].get_images()


@pytest.mark.parametrize("select,expected", [
    ("", [1, 2, 3]), ("1-2", [1, 2]), ("2-", [2, 3]), ("-2", [1, 2]),
    ("3,1,3", [3, 1, 3]), ("1,3", [1, 3]), ("0,2,9", [2]),
])
def test_split_extract_delete_reorder(client, pdf_bytes, select, expected, assert_pdf):
    response = client.post("/pdftools/api/pages", files={"file": ("pages.pdf", pdf_bytes[3])},
                           data={"select": select})
    assert_pdf(response, len(expected))
    with fitz.open(stream=response.content, filetype="pdf") as document:
        assert [page.get_text().strip() for page in document] == [f"Smoke page {i}" for i in expected]


@pytest.mark.parametrize("angle", [0, 90, 180, 270, -90, 450])
def test_rotate_selected_pages(client, pdf_bytes, angle, assert_pdf):
    response = client.post("/pdftools/api/pages", files={"file": ("pages.pdf", pdf_bytes[3])},
                           data={"select": "1,3", "rotate": angle})
    assert_pdf(response, 2)
    with fitz.open(stream=response.content, filetype="pdf") as document:
        assert [page.rotation for page in document] == [angle % 360] * 2


@pytest.mark.parametrize("level,dpi", [("light", 120), ("strong", 72),
                                        ("strong", 1), ("strong", 999)])
def test_compress(client, pdf_bytes, level, dpi, assert_pdf):
    response = client.post("/pdftools/api/compress", files={"file": ("pages.pdf", pdf_bytes[3])},
                           data={"level": level, "dpi": dpi})
    assert_pdf(response, 3)
    with fitz.open(stream=response.content, filetype="pdf") as document:
        for page in document:
            assert page.rect == fitz.Rect(0, 0, 240, 320)
            if level == "light":
                assert "Smoke page" in page.get_text()
            else:
                image = page.get_images(full=True)[0]
                effective_dpi = min(300, max(60, dpi))
                assert image[2:4] == (int(240 * effective_dpi / 72 + 0.999),
                                      int(320 * effective_dpi / 72 + 0.999))
    # A tiny vector document may grow when rasterized; size reduction is not guaranteed.


@pytest.mark.parametrize("fmt", ["png", "jpg"])
@pytest.mark.parametrize("pages", [1, 3])
@pytest.mark.parametrize("dpi", [72, 1, 999])
def test_pdf_to_images(client, pdf_bytes, fmt, pages, dpi, assert_image, assert_response):
    response = client.post("/pdftools/api/to_images", files={"file": ("pages.pdf", pdf_bytes[pages])},
                           data={"fmt": fmt, "dpi": dpi})
    effective_dpi = min(600, max(36, dpi))
    expected_size = (int(240 * effective_dpi / 72 + 0.999),
                     int(320 * effective_dpi / 72 + 0.999))
    if pages == 1:
        assert_image(response, "JPEG" if fmt == "jpg" else "PNG", expected_size)
    else:
        assert_response(response, media="application/zip")
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            assert archive.namelist() == [f"page_{i:03d}.{fmt}" for i in range(1, 4)]
            assert archive.testzip() is None
            for name in archive.namelist():
                with Image.open(io.BytesIO(archive.read(name))) as image:
                    assert image.format == ("JPEG" if fmt == "jpg" else "PNG")
                    assert image.size == expected_size
                    image.load()


@pytest.mark.parametrize("formats", [("png",), ("jpg",), ("png", "jpg")])
def test_images_to_pdf(client, image_bytes, formats, assert_pdf):
    response = client.post("/pdftools/api/from_images", files=[
        ("files", (f"page{i}.{fmt}", image_bytes[fmt])) for i, fmt in enumerate(formats)])
    assert_pdf(response, len(formats))
    with fitz.open(stream=response.content, filetype="pdf") as document:
        assert all(page.get_images() for page in document)


@pytest.mark.parametrize("select", ["word", "9", "3-1"])
def test_invalid_selection(client, pdf_bytes, select, assert_response):
    assert_response(client.post("/pdftools/api/pages", files={"file": ("pages.pdf", pdf_bytes[3])},
                                data={"select": select}), 400)


@pytest.mark.parametrize("route", ["merge", "pages", "compress", "to_images", "from_images"])
def test_missing_files(client, route, assert_response):
    assert_response(client.post("/pdftools/api/" + route), 422)
