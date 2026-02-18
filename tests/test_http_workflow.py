from __future__ import annotations

from urllib.request import Request, urlopen


def _post(url: str):
    req = Request(url, method="POST")
    return urlopen(req)


def test_dashboard_available_over_http(server):
    with urlopen(f"{server['base_url']}/", timeout=3) as response:
        body = response.read().decode("utf-8")

    assert response.status == 200
    assert "PlantCamera Dashboard" in body
    assert "Images captured:" in body


def test_capture_now_creates_frame_and_reports_notice(server):
    with _post(f"{server['base_url']}/capture-now") as response:
        assert response.url.startswith(f"{server['base_url']}/?notice=OK%3A")

    with urlopen(f"{server['base_url']}/", timeout=3) as response:
        body = response.read().decode("utf-8")

    assert "Images captured: 1" in body


def test_convert_now_creates_video_and_clears_frames(server):
    _post(f"{server['base_url']}/capture-now").read()

    with _post(f"{server['base_url']}/convert-now") as response:
        assert response.url.startswith(f"{server['base_url']}/?notice=OK%3A")

    with urlopen(f"{server['base_url']}/", timeout=3) as response:
        body = response.read().decode("utf-8")

    assert "timelapse_" in body
    assert "Images captured: 0" in body


def test_delete_video_uses_http_endpoint(server):
    _post(f"{server['base_url']}/capture-now").read()
    _post(f"{server['base_url']}/convert-now").read()

    with urlopen(f"{server['base_url']}/", timeout=3) as response:
        body = response.read().decode("utf-8")

    marker = "/delete/"
    start = body.index(marker) + len(marker)
    end = body.index("'", start)
    file_name = body[start:end]

    _post(f"{server['base_url']}/delete/{file_name}").read()

    with urlopen(f"{server['base_url']}/", timeout=3) as response:
        body_after = response.read().decode("utf-8")

    assert f"/delete/{file_name}" not in body_after
