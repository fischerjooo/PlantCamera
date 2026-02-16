from __future__ import annotations

import html
import os
import sys
import threading
import time
from collections import deque
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from src.git_updater import GitCommandError, get_repo_status, update_repo
from src.timelapse_manager import TimeLapseManager


LIVE_VIEW_FILENAME = "live.jpg"
DASHBOARD_REFRESH_SECONDS = 5
MAX_LOG_MESSAGES = 100


def _restart_process() -> None:
    os.execv(sys.executable, [sys.executable, *sys.argv])


def _html_page(
    update_endpoint: str,
    repo_branch_text: str,
    repo_commit_text: str,
    timelapse_status: dict[str, str | int | float | None],
    videos: list[str],
    logs: list[str],
    notice: str | None = None,
) -> bytes:
    safe_notice = f"<p class='notice'>{html.escape(notice)}</p>" if notice else ""

    video_rows = ""
    for video in videos:
        escaped_video = html.escape(video)
        quoted_video = quote(video)
        video_rows += (
            "<tr>"
            f"<td>{escaped_video}</td>"
            "<td><div class='actions'>"
            f"<a href='/videos/{quoted_video}'>Watch</a>"
            f"<a href='/download/{quoted_video}'>Download</a>"
            f"<form method='post' action='/delete/{quoted_video}'>"
            "<button type='submit' class='danger'>Delete</button>"
            "</form>"
            "</div></td>"
            "</tr>"
        )

    videos_section = (
        "<table><thead><tr><th>File</th><th>Actions</th></tr></thead><tbody>"
        f"{video_rows}</tbody></table>"
        if video_rows
        else "<p class='meta'>No videos generated yet.</p>"
    )

    log_lines = "\n".join(html.escape(line) for line in logs)

    html_text = f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>PlantCamera Dashboard</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 0; background: #f2f4f8; color: #1f2937; }}
    main {{ max-width: 1100px; margin: 0 auto; padding: 16px; }}
    section {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 10px; padding: 14px; margin-bottom: 14px; }}
    .notice {{ background: #dbeafe; border: 1px solid #93c5fd; padding: 10px; border-radius: 6px; }}
    .meta {{ margin: 5px 0; color: #374151; }}
    .error {{ color: #b91c1c; font-weight: 700; }}
    .ok {{ color: #166534; font-weight: 700; }}
    .logs {{ background: #0f172a; color: #e2e8f0; padding: 10px; border-radius: 8px; max-height: 250px; overflow: auto; white-space: pre-wrap; font-size: 13px; }}
    img {{ width: 100%; max-width: 960px; border-radius: 8px; border: 1px solid #d1d5db; background: #fff; display: block; margin: 0 auto; transform: rotate(-90deg); transform-origin: center; }}
    .toolbar {{ display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }}
    button {{ border: none; padding: 8px 14px; border-radius: 6px; background: #22c55e; color: #06240f; font-weight: 700; cursor: pointer; }}
    button:hover {{ background: #16a34a; color: #fff; }}
    .danger {{ background: #dc2626; color: #fff; }}
    .danger:hover {{ background: #b91c1c; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ border-bottom: 1px solid #e5e7eb; padding: 8px; text-align: left; }}
    .actions {{ display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }}
    a {{ color: #2563eb; text-decoration: none; }}
  </style>
</head>
<body>
  <main>
    {safe_notice}

    <section>
      <h2>Live View</h2>
      <img id=\"liveView\" src=\"/{LIVE_VIEW_FILENAME}?t={int(time.time())}\" alt=\"Live camera preview\" />
      {f"<p class='meta error'>Live view error: {html.escape(str(timelapse_status['last_live_view_error']))}</p>" if timelapse_status['last_live_view_error'] else ""}
      <p class=\"meta\">Live view path: DCIM/PlantCamera/live_view.jpg</p>
      <p class=\"meta\">Last successful timelapse capture: <span class=\"ok\">{html.escape(str(timelapse_status['last_capture_timestamp']))}</span></p>
      {f"<p class='meta error'>Last timelapse capture error: {html.escape(str(timelapse_status['last_capture_error']))}</p>" if timelapse_status['last_capture_error'] else ""}
      {f"<p class='meta error'>Last encode error: {html.escape(str(timelapse_status['last_encode_error']))}</p>" if timelapse_status['last_encode_error'] else ""}
    </section>

    <section>
      <h2>Time lapse Management</h2>
      <p class=\"meta\">Images captured: {timelapse_status['collected_images']}</p>
      <p class=\"meta\">Capture interval: {timelapse_status['capture_interval_minutes']} minutes</p>
      <p class=\"meta\">Session duration (image count): {timelapse_status['session_image_count']} images</p>
      <form method=\"post\" action=\"/capture-now\"> 
        <button type=\"submit\">Take timelapse photo now</button>
      </form>
    </section>

    <section>
      <h2>Video Management</h2>
      <form method=\"post\" action=\"/convert-now\">
        <button type=\"submit\">Convert</button>
      </form>
      {videos_section}
    </section>

    <section>
      <h2>Application</h2>
      <div class=\"toolbar\">
        <form id=\"updateForm\" method=\"post\" action=\"{html.escape(update_endpoint)}\">
          <button type=\"submit\">Update</button>
        </form>
        <div>
          <p class=\"meta\">{html.escape(repo_branch_text)}</p>
          <p class=\"meta\">{html.escape(repo_commit_text)}</p>
        </div>
      </div>
      <h3>Logs (last {MAX_LOG_MESSAGES})</h3>
      <div class=\"logs\">{log_lines if log_lines else 'No logs yet.'}</div>
    </section>
  </main>

  <script>
    setInterval(() => {{
      const liveView = document.getElementById('liveView');
      liveView.src = '/{LIVE_VIEW_FILENAME}?t=' + Date.now();
    }}, {DASHBOARD_REFRESH_SECONDS * 1000});

    const updateForm = document.getElementById('updateForm');
    if (updateForm) {{
      updateForm.addEventListener('submit', async (event) => {{
        event.preventDefault();
        await fetch(updateForm.action, {{ method: 'POST' }});
        setTimeout(() => window.location.reload(), 5000);
      }});
    }}
  </script>
</body>
</html>
"""
    return html_text.encode("utf-8")


def run_web_server(
    host: str,
    port: int,
    repo_root: Path,
    remote_name: str,
    main_branch: str,
    update_endpoint: str,
) -> None:
    app_logs: deque[str] = deque(maxlen=MAX_LOG_MESSAGES)
    logs_lock = threading.Lock()

    def log_event(message: str) -> None:
        entry = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}"
        with logs_lock:
            app_logs.append(entry)
        print(entry)

    timelapse_manager = TimeLapseManager(repo_root=repo_root, log_callback=log_event)

    def recent_logs() -> list[str]:
        with logs_lock:
            return list(app_logs)

    def perform_update_and_restart() -> None:
        time.sleep(0.5)
        log_event("Update requested")
        update_repo(repo_root, remote_name=remote_name, main_branch=main_branch)
        _restart_process()

    class UpdaterRequestHandler(BaseHTTPRequestHandler):
        def _send_bytes(self, body: bytes, content_type: str) -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_file(self, file_path: Path, content_type: str, as_attachment: bool = False) -> None:
            body = file_path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            if as_attachment:
                self.send_header("Content-Disposition", f"attachment; filename={file_path.name}")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            clean_path = parsed.path

            if clean_path == "/":
                try:
                    status = get_repo_status(repo_root)
                    repo_branch = f"Branch: {status.branch}"
                    repo_commit = f"Last commit: {status.last_commit_date}"
                except GitCommandError as error:
                    repo_branch = "Branch: unknown"
                    repo_commit = f"Git error: {error}"

                notice = parse_qs(parsed.query).get("notice", [None])[0]
                page = _html_page(
                    update_endpoint=update_endpoint,
                    repo_branch_text=repo_branch,
                    repo_commit_text=repo_commit,
                    timelapse_status=timelapse_manager.get_status(),
                    videos=timelapse_manager.list_videos(),
                    logs=recent_logs(),
                    notice=notice,
                )
                self._send_bytes(page, "text/html; charset=utf-8")
                return

            if clean_path == f"/{LIVE_VIEW_FILENAME}":
                if not timelapse_manager.live_image_path.exists():
                    self.send_error(HTTPStatus.NOT_FOUND, "Live view image not found yet")
                    return

                image = timelapse_manager.live_image_path.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
                self.send_header("Pragma", "no-cache")
                self.send_header("Expires", "0")
                self.send_header("Content-Length", str(len(image)))
                self.end_headers()
                self.wfile.write(image)
                return

            if clean_path.startswith("/videos/"):
                video_name = unquote(clean_path.removeprefix("/videos/"))
                try:
                    path = timelapse_manager.get_video_path(video_name)
                except (ValueError, FileNotFoundError):
                    self.send_error(HTTPStatus.NOT_FOUND, "Video not found")
                    return
                self._send_file(path, "video/mp4", as_attachment=False)
                return

            if clean_path.startswith("/download/"):
                video_name = unquote(clean_path.removeprefix("/download/"))
                try:
                    path = timelapse_manager.get_video_path(video_name)
                except (ValueError, FileNotFoundError):
                    self.send_error(HTTPStatus.NOT_FOUND, "Video not found")
                    return
                self._send_file(path, "video/mp4", as_attachment=True)
                return

            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            clean_path = parsed.path

            if clean_path == update_endpoint:
                self.send_response(HTTPStatus.SEE_OTHER)
                self.send_header("Location", "/")
                self.end_headers()

                thread = threading.Thread(target=perform_update_and_restart, daemon=True)
                thread.start()
                return

            if clean_path == "/capture-now":
                ok, message = timelapse_manager.trigger_capture_now()
                status_prefix = "OK" if ok else "ERROR"
                encoded_notice = quote(f"{status_prefix}: {message}")
                self.send_response(HTTPStatus.SEE_OTHER)
                self.send_header("Location", f"/?notice={encoded_notice}")
                self.end_headers()
                return

            if clean_path == "/convert-now":
                ok, message = timelapse_manager.trigger_convert_now()
                status_prefix = "OK" if ok else "ERROR"
                encoded_notice = quote(f"{status_prefix}: {message}")
                self.send_response(HTTPStatus.SEE_OTHER)
                self.send_header("Location", f"/?notice={encoded_notice}")
                self.end_headers()
                return

            if clean_path.startswith("/delete/"):
                video_name = unquote(clean_path.removeprefix("/delete/"))
                try:
                    timelapse_manager.delete_video(video_name)
                except (ValueError, FileNotFoundError):
                    self.send_error(HTTPStatus.NOT_FOUND, "Video not found")
                    return

                self.send_response(HTTPStatus.SEE_OTHER)
                self.send_header("Location", "/")
                self.end_headers()
                return

            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

        def log_message(self, format_: str, *args: object) -> None:
            print(f"[web] {self.address_string()} - {format_ % args}")

    log_event(f"Starting server on http://{host}:{port}")
    timelapse_manager.start()
    server = ThreadingHTTPServer((host, port), UpdaterRequestHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log_event("Stopping server...")
    finally:
        timelapse_manager.stop()
        server.server_close()
