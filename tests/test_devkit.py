def test_index(client, assert_response):
    response = assert_response(client.get("/devkit/"), media="text/html")
    assert "<html" in response.text.lower()
    assert "<script" in response.text.lower()


def test_health(client, assert_response):
    assert assert_response(client.get("/devkit/healthz")).json() == {"ok": True}
