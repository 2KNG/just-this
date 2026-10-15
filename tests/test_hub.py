import pytest

TOOLS = {"imgconv", "webcrop", "pdftools", "vidconv", "ytdl", "devkit", "qr"}


def test_index(client, assert_response):
    response = assert_response(client.get("/"), media="text/html")
    for slug in TOOLS:
        assert f"/{slug}/" in response.text


def test_health_and_mounts(client, assert_response):
    body = assert_response(client.get("/healthz")).json()
    assert body["ok"] is True
    assert set(body["mounted"]) == TOOLS
    assert body["mount_errors"] == {}


def test_tool_catalog(client, assert_response):
    body = assert_response(client.get("/api/tools")).json()
    assert body["total"] == len(body["tools"])
    mounted = {tool["slug"]: tool for tool in body["tools"] if tool["_mounted"]}
    assert set(mounted) == TOOLS
    assert body["mounted"] == len(TOOLS)
    for slug, tool in mounted.items():
        assert tool["_open"] == f"/{slug}/"
        assert tool["_needs_deps"] is False


@pytest.mark.parametrize("prefix", ["", *sorted(TOOLS)])
def test_openapi(client, prefix, assert_response):
    body = assert_response(client.get(f"{prefix and '/' + prefix}/openapi.json")).json()
    assert body["openapi"].startswith("3.")
    assert "/healthz" in body["paths"]


@pytest.mark.parametrize("path,media", [
    ("/static/style.css", "text/css"),
    ("/imgconv/static/cropper.min.js", "text/javascript"),
    ("/webcrop/static/cropper.min.css", "text/css"),
    ("/pdftools/static/index.html", "text/html"),
])
def test_mounted_static(client, path, media, assert_response):
    assert_response(client.get(path), media=media)


def test_missing_route(client, assert_response):
    assert_response(client.get("/no-such-tool/"), 404)
