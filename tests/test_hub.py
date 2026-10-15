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


def test_pin_gate_flow(client, monkeypatch, assert_response):
    monkeypatch.setenv("JT_PIN", "4826")
    client.cookies.clear()

    # healthz and static remain public
    assert_response(client.get("/healthz"))
    assert_response(client.get("/static/ui.css"), media="text/css")

    # unauthenticated page & mounted tool return 401 HTML lock screen
    r_home = client.get("/")
    assert r_home.status_code == 401
    assert "PIN 잠금" in r_home.text

    r_tool = client.get("/ytdl/?tab=playlist")
    assert r_tool.status_code == 401
    assert "/ytdl/?tab=playlist" in r_tool.text

    # unauthenticated API returns 401 JSON
    r_api = client.get("/api/tools")
    assert r_api.status_code == 401
    assert r_api.json()["detail"] == "PIN 인증이 필요합니다."

    # header X-JT-PIN bypasses lock
    assert_response(client.get("/api/tools", headers={"X-JT-PIN": "4826"}))

    # wrong PIN stays 401
    r_bad = client.post("/auth/pin", data={"pin": "0000", "next": "/ytdl/"}, follow_redirects=False)
    assert r_bad.status_code == 401
    assert "올바르지 않습니다" in r_bad.text

    # right PIN sets cookie & redirects to next
    r_ok = client.post("/auth/pin", data={"pin": "4826", "next": "/ytdl/"}, follow_redirects=False)
    assert r_ok.status_code == 303
    assert r_ok.headers["location"] == "/ytdl/"
    assert "jt_pin" in r_ok.cookies

    # authenticated cookie grants access to hub and mounted tools
    assert_response(client.get("/"), media="text/html")
    assert_response(client.get("/ytdl/"), media="text/html")
    assert_response(client.get("/api/tools"))

    # logout clears cookie
    r_out = client.post("/auth/logout", follow_redirects=False)
    assert r_out.status_code == 303
    client.cookies.clear()
    assert client.get("/").status_code == 401
