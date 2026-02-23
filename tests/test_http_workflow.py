from __future__ import annotations

import json
import re
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def _post(url: str):
    req = Request(url, method="POST")
    return urlopen(req)


def _post_form(url: str, payload: dict[str, str]):
    req = Request(url, method="POST", data=urlencode(payload).encode("utf-8"), headers={"Content-Type": "application/x-www-form-urlencoded"})
    return urlopen(req)


def _post_json(url: str, payload: dict):
    req = Request(url, method="POST", data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
    with urlopen(req) as response:
        return json.loads(response.read().decode("utf-8"))


def _extract_name_from_dashboard(body: str, marker: str) -> str:
    start = body.index(marker) + len(marker)
    end = body.index("'", start)
    return body[start:end]


def _list_video_files(server: dict[str, str]):
    return sorted(p.name for p in (server["media_dir"] / "videos").glob("*.mp4"))


def _list_image_files(server: dict[str, str]):
    return sorted(p.name for p in (server["media_dir"] / "images").glob("*.jpg"))


def _create_video(server: dict[str, str]) -> str:
    _post(f"{server['base_url']}/capture-now").read()
    _post(f"{server['base_url']}/convert-now").read()

    with urlopen(f"{server['base_url']}/?page=TimeLapse", timeout=3) as response:
        body = response.read().decode("utf-8")

    return _extract_name_from_dashboard(body, "/delete/")


def _create_image(server: dict[str, str]) -> str:
    _post(f"{server['base_url']}/capture-now").read()
    with urlopen(f"{server['base_url']}/?page=TimeLapse", timeout=3) as response:
        body = response.read().decode("utf-8")
    return _extract_name_from_dashboard(body, "/delete-image/")


def test_dashboard_available_over_http(server):
    with urlopen(f"{server['base_url']}/?page=TimeLapse", timeout=3) as response:
        body = response.read().decode("utf-8")

    assert response.status == 200
    assert "PlantCamera Dashboard" in body
    assert "Images captured:" in body
    assert "Capture interval: 15 minutes" in body
    assert "Delete all timelapse images" in body
    assert "Photo Management" in body


def test_navigation_bar_has_four_pages_and_switches_sections(server):
    with urlopen(f"{server['base_url']}/?page=Live", timeout=3) as response:
        live = response.read().decode("utf-8")
    with urlopen(f"{server['base_url']}/?page=TimeLapse", timeout=3) as response:
        timelapse = response.read().decode("utf-8")
    with urlopen(f"{server['base_url']}/?page=Config", timeout=3) as response:
        config = response.read().decode("utf-8")
    with urlopen(f"{server['base_url']}/?page=App", timeout=3) as response:
        app = response.read().decode("utf-8")

    assert 'href="/?page=Live"' in live
    assert 'href="/?page=TimeLapse"' in live
    assert 'href="/?page=Config"' in live
    assert 'href="/?page=App"' in live
    assert "<h2>Live View</h2>" in live
    assert "<h2>Time lapse Management</h2>" in timelapse
    assert "<h2>Photo Management</h2>" in timelapse
    assert "<h2>Config</h2>" in config
    assert "<h2>Application</h2>" in app


def test_video_and_photo_actions_use_colored_watch_download_buttons(server):
    _create_image(server)

    with urlopen(f"{server['base_url']}/?page=TimeLapse", timeout=3) as response:
        image_body = response.read().decode("utf-8")

    assert "href='/images/" in image_body
    assert "class='btn watch-btn'" in image_body
    assert "class='btn download-btn'" in image_body

    _create_video(server)

    with urlopen(f"{server['base_url']}/?page=TimeLapse", timeout=3) as response:
        video_body = response.read().decode("utf-8")

    assert "href='/videos/" in video_body
    assert "class='btn watch-btn'" in video_body
    assert "class='btn download-btn'" in video_body


def test_capture_now_creates_image_with_simplified_name(server):
    with _post(f"{server['base_url']}/capture-now") as response:
        assert response.url.startswith(f"{server['base_url']}/?notice=OK%3A")

    files = _list_image_files(server)
    assert len(files) == 1
    assert re.match(r"^image_\d{6}_\d{6}\.jpg$", files[0])


def test_camera_simulator_is_controllable_via_http(server):
    state = _post_json(f"{server['base_url']}/__camera", {"black_ratio": 0.95, "fail_next_capture": True})
    assert state["black_ratio"] == 0.95
    assert state["fail_next_capture"] is True

    reset = _post_json(f"{server['base_url']}/__camera", {"black_ratio": 0.0, "fail_next_capture": False})
    assert reset["black_ratio"] == 0.0
    assert reset["fail_next_capture"] is False


def test_black_images_are_discarded_after_capture(server):
    _post_json(f"{server['base_url']}/__camera", {"black_ratio": 0.95})
    _post(f"{server['base_url']}/capture-now").read()

    with urlopen(f"{server['base_url']}/?page=TimeLapse", timeout=3) as response:
        body = response.read().decode("utf-8")

    assert "Images captured: 0" in body

    with urlopen(f"{server['base_url']}/?page=App", timeout=3) as response:
        app_body = response.read().decode("utf-8")
    assert "Discarded image" in app_body


def test_captured_images_are_rotated_left(server):
    _post_json(f"{server['base_url']}/__camera", {"black_ratio": 0.0})
    _post(f"{server['base_url']}/capture-now").read()

    image = next((server["media_dir"] / "images").glob("image_*.jpg"))
    payload = image.read_bytes()
    assert b"ROTATE_LEFT_90=1" in payload
    assert b"NORMALIZED_FULL_HD=1920x1080" in payload


def test_photo_watch_download_and_delete_endpoints(server):
    file_name = _create_image(server)

    with urlopen(f"{server['base_url']}/images/{file_name}", timeout=3) as watch:
        watch_body = watch.read()
    assert watch.status == 200
    assert watch.headers.get("Content-Type") == "image/jpeg"
    assert watch_body.startswith(b"\xff\xd8\xff")

    with urlopen(f"{server['base_url']}/download-image/{file_name}", timeout=3) as download:
        download_body = download.read()
    assert download.status == 200
    assert download.headers.get("Content-Type") == "image/jpeg"
    assert download.headers.get("Content-Disposition") == f"attachment; filename={file_name}"
    assert download_body.startswith(b"\xff\xd8\xff")

    _post(f"{server['base_url']}/delete-image/{file_name}").read()
    with urlopen(f"{server['base_url']}/?page=TimeLapse", timeout=3) as response:
        body = response.read().decode("utf-8")
    assert f"/delete-image/{file_name}" not in body


def test_delete_all_timelapse_images_button_endpoint(server):
    _post(f"{server['base_url']}/capture-now").read()
    _post(f"{server['base_url']}/capture-now").read()

    with _post(f"{server['base_url']}/delete-all-images") as response:
        assert response.url.startswith(f"{server['base_url']}/?notice=OK%3A")

    with urlopen(f"{server['base_url']}/?page=TimeLapse", timeout=3) as dashboard:
        body = dashboard.read().decode("utf-8")
    assert "Images captured: 0" in body


def test_convert_now_creates_video_with_simplified_name_and_clears_images(server):
    _post(f"{server['base_url']}/capture-now").read()

    with _post(f"{server['base_url']}/convert-now") as response:
        assert response.url.startswith(f"{server['base_url']}/?notice=OK%3A")

    video_files = _list_video_files(server)
    assert len(video_files) == 1
    assert re.match(r"^video_\d{6}_\d{6}_\d{6}_\d{6}\.mp4$", video_files[0])

    with urlopen(f"{server['base_url']}/?page=TimeLapse", timeout=3) as response:
        body = response.read().decode("utf-8")
    assert "Images captured: 0" in body


def test_delete_video_uses_http_endpoint(server):
    file_name = _create_video(server)

    _post(f"{server['base_url']}/delete/{file_name}").read()

    with urlopen(f"{server['base_url']}/?page=TimeLapse", timeout=3) as response:
        body_after = response.read().decode("utf-8")

    assert f"/delete/{file_name}" not in body_after


def test_live_view_endpoint_serves_jpeg(server):
    deadline = time.time() + 5
    while True:
        try:
            with urlopen(f"{server['base_url']}/live.jpg", timeout=3) as response:
                payload = response.read()
                content_type = response.headers.get("Content-Type")
            break
        except HTTPError as error:
            if error.code != 404 or time.time() >= deadline:
                raise
            time.sleep(0.1)

    assert response.status == 200
    assert content_type == "image/jpeg"
    assert payload.startswith(b"\xff\xd8\xff")


def test_video_watch_and_download_endpoints(server):
    file_name = _create_video(server)

    with urlopen(f"{server['base_url']}/videos/{file_name}", timeout=3) as watch:
        watch_body = watch.read()

    assert watch.status == 200
    assert watch.headers.get("Content-Type") == "video/mp4"
    assert watch_body.startswith(b"FAKE-MP4")

    with urlopen(f"{server['base_url']}/download/{file_name}", timeout=3) as download:
        download_body = download.read()

    assert download.status == 200
    assert download.headers.get("Content-Type") == "video/mp4"
    assert download.headers.get("Content-Disposition") == f"attachment; filename={file_name}"
    assert download_body.startswith(b"FAKE-MP4")


def test_convert_now_with_no_images_returns_error_notice(server):
    _post(f"{server['base_url']}/convert-now").read()

    with _post(f"{server['base_url']}/convert-now") as response:
        final_url = response.url

    assert "notice=ERROR%3A" in final_url
    assert "No%20collected%20images%20available%20for%20conversion." in final_url


def test_merge_videos_merges_in_chronological_order_and_deletes_sources(server):
    _create_video(server)
    time.sleep(1.1)
    _create_video(server)

    before = _list_video_files(server)
    assert len(before) == 2

    with _post(f"{server['base_url']}/merge-videos") as response:
        assert response.url.startswith(f"{server['base_url']}/?notice=OK%3A")

    after = _list_video_files(server)
    assert len(after) == 1
    assert after[0].startswith("merged_")

    merged_payload = (server["media_dir"] / "videos" / after[0]).read_text(encoding="utf-8")
    chronological = sorted(before)
    assert f"MERGED:{chronological[0]}|{chronological[1]}" in merged_payload


def test_merge_videos_requires_at_least_two_videos(server):
    _create_video(server)

    with _post(f"{server['base_url']}/merge-videos") as response:
        final_url = response.url

    assert "notice=ERROR%3A" in final_url
    assert "Need%20at%20least%202%20videos%20to%20merge." in final_url


def test_config_page_save_updates_runtime_values_and_persists_file(server):
    with _post_form(
        f"{server['base_url']}/config/save",
        {
            "capture_interval_seconds": "120",
            "rotation_degrees": "180",
            "session_image_count": "12",
            "black_detection_percentage": "75",
        },
    ) as response:
        assert "page=Config" in response.url
        assert "notice=OK%3A" in response.url

    with urlopen(f"{server['base_url']}/?page=Config", timeout=3) as response:
        body = response.read().decode("utf-8")

    assert "value='120'" in body
    assert "value='12'" in body
    assert "value='75.0'" in body
    assert "<option value='180' selected>180</option>" in body

    config_file = server["media_dir"] / "config.json"
    config_text = config_file.read_text(encoding="utf-8")
    assert '"capture_interval_seconds": 120' in config_text
    assert '"rotation_degrees": 180' in config_text
    assert '"session_image_count": 12' in config_text
    assert '"black_detection_percentage": 75.0' in config_text


def test_config_is_loaded_after_server_restart(restartable_server):
    with _post_form(
        f"{restartable_server['base_url']}/config/save",
        {
            "capture_interval_seconds": "240",
            "rotation_degrees": "270",
            "session_image_count": "33",
            "black_detection_percentage": "66.5",
        },
    ) as response:
        assert "notice=OK%3A" in response.url

    restarted = restartable_server["restart"]()

    with urlopen(f"{restarted['base_url']}/?page=Config", timeout=3) as response:
        body = response.read().decode("utf-8")

    assert "value='240'" in body
    assert "value='33'" in body
    assert "value='66.5'" in body
    assert "<option value='270' selected>270</option>" in body


def test_missing_video_and_image_endpoints_return_404(server):
    missing_video = "does-not-exist.mp4"
    missing_image = "does-not-exist.jpg"

    for path in (
        f"/videos/{missing_video}",
        f"/download/{missing_video}",
        f"/delete/{missing_video}",
        f"/images/{missing_image}",
        f"/download-image/{missing_image}",
        f"/delete-image/{missing_image}",
    ):
        url = f"{server['base_url']}{path}"
        request = Request(url, method="POST") if path.startswith("/delete") else url
        try:
            urlopen(request, timeout=3)
            raise AssertionError(f"Expected HTTPError for {path}")
        except HTTPError as error:
            assert error.code == 404


def test_convert_now_rejects_tiny_output_and_reports_error(server_with_tiny_video):
    _post(f"{server_with_tiny_video['base_url']}/capture-now").read()

    with _post(f"{server_with_tiny_video['base_url']}/convert-now") as response:
        final_url = response.url

    assert "notice=ERROR%3A" in final_url
    assert "Generated%20video%20file%20is%20too%20small" in final_url

    with urlopen(f"{server_with_tiny_video['base_url']}/?page=App", timeout=3) as dashboard:
        body = dashboard.read().decode("utf-8")

    assert "Generated video file is too small" in body
    assert "Encode failed:" in body
