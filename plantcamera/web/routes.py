from __future__ import annotations

from http import HTTPStatus
from urllib.parse import parse_qs, quote, unquote, urlparse

from plantcamera.infra.git_cli import GitCommandError
from plantcamera.web.views import render_dashboard


def dispatch(handler, method: str, raw_path: str) -> None:
    parsed = urlparse(raw_path)
    path = parsed.path
    app = handler.app

    if app.test_mode and method == "GET" and path == "/__health":
        handler.send_bytes(b"ok", "text/plain; charset=utf-8")
        return

    if app.test_mode and method == "POST" and path == "/__shutdown":
        handler.send_response(HTTPStatus.OK)
        handler.end_headers()
        app.shutdown_async()
        return

    if method == "GET" and path == "/":
        try:
            status = app.updater.get_status()
            repo_branch = f"Branch: {status.branch}"
            repo_commit = f"Last commit: {status.last_commit_date}"
        except GitCommandError as error:
            repo_branch = "Branch: unknown"
            repo_commit = f"Git error: {error}"
        notice = parse_qs(parsed.query).get("notice", [None])[0]
        page = render_dashboard(
            update_endpoint=app.config.update_endpoint,
            repo_branch_text=repo_branch,
            repo_commit_text=repo_commit,
            status=app.timelapse.get_status(),
            videos=app.timelapse.list_videos(),
            logs=app.recent_logs(),
            notice=notice,
        )
        handler.send_bytes(page, "text/html; charset=utf-8")
        return

    if method == "GET" and path == "/live.jpg":
        if not app.timelapse.live_image_path.exists():
            handler.send_error(HTTPStatus.NOT_FOUND, "Live view image not found yet")
            return
        image = app.timelapse.live_image_path.read_bytes()
        handler.send_response(HTTPStatus.OK)
        handler.send_header("Content-Type", "image/jpeg")
        handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        handler.send_header("Content-Length", str(len(image)))
        handler.end_headers()
        handler.wfile.write(image)
        return

    if method == "GET" and path.startswith("/videos/"):
        return _serve_video(handler, unquote(path.removeprefix("/videos/")), False)
    if method == "GET" and path.startswith("/download/"):
        return _serve_video(handler, unquote(path.removeprefix("/download/")), True)

    if method == "POST" and path == "/capture-now":
        ok, message = app.timelapse.trigger_capture_now()
        handler.redirect_with_notice(ok, message)
        return

    if method == "POST" and path == "/convert-now":
        ok, message = app.timelapse.trigger_convert_now()
        handler.redirect_with_notice(ok, message)
        return

    if method == "POST" and path == app.config.update_endpoint:
        handler.redirect("/")
        app.run_update_async()
        return

    if method == "POST" and path.startswith("/delete/"):
        try:
            app.timelapse.delete_video(unquote(path.removeprefix("/delete/")))
        except (ValueError, FileNotFoundError):
            handler.send_error(HTTPStatus.NOT_FOUND, "Video not found")
            return
        handler.redirect("/")
        return

    handler.send_error(HTTPStatus.NOT_FOUND, "Not Found")


def _serve_video(handler, name: str, as_attachment: bool) -> None:
    try:
        path = handler.app.timelapse.get_video_path(name)
    except (ValueError, FileNotFoundError):
        handler.send_error(HTTPStatus.NOT_FOUND, "Video not found")
        return
    body = path.read_bytes()
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", "video/mp4")
    if as_attachment:
        handler.send_header("Content-Disposition", f"attachment; filename={path.name}")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)
