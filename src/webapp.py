from __future__ import annotations

import html
import os
import subprocess
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from src.git_updater import GitCommandError, get_repo_status, update_repo


LIVE_VIEW_FILENAME = "live_view.jpg"
CAPTURE_INTERVAL_SECONDS = 5


def _restart_process() -> None:
    os.execv(sys.executable, [sys.executable, *sys.argv])


def run_web_server(
    host: str,
    port: int,
    repo_root: Path,
    remote_name: str,
    main_branch: str,
    update_endpoint: str,
) -> None:
    live_view_path = repo_root / LIVE_VIEW_FILENAME
    capture_stop = threading.Event()

    def capture_live_view_forever() -> None:
        while not capture_stop.is_set():
            try:
                subprocess.run(
                    ["termux-camera-photo", str(live_view_path)],
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except FileNotFoundError:
                print("[camera] termux-camera-photo not found. Live view capture is disabled.")
                return
            except subprocess.CalledProcessError as error:
                stderr = error.stderr.strip() if error.stderr else "unknown error"
                print(f"[camera] Failed to capture live view image: {stderr}")

            capture_stop.wait(CAPTURE_INTERVAL_SECONDS)

    def render_page(message: str | None = None) -> bytes:
        try:
            status = get_repo_status(repo_root)
            status_text = f"Branch: {status.branch}"
            commit_text = f"Last commit: {status.last_commit_date}"
        except GitCommandError as error:
            status_text = "Branch: unknown"
            commit_text = f"Git error: {error}"

        notice = f"<p class='notice'>{html.escape(message)}</p>" if message else ""

        html_page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PlantCamera Updater</title>
  <style>
    body {{ font-family: sans-serif; margin: 0; background: #f2f4f8; color: #202124; }}
    main {{ padding: 0 20px 20px; }}
    p {{ margin: 4px 0 0; }}
    .notice {{ background: #dbeafe; border: 1px solid #93c5fd; padding: 10px; border-radius: 6px; }}
    .update_status {{ margin-top: 14px; padding: 12px; border-radius: 8px; background: #dcfce7; display: flex; align-items: center; gap: 14px; }}
    .status_text p {{ margin: 2px 0; }}
    .actions {{ margin: 0; }}
    button {{ border: none; padding: 10px 16px; border-radius: 6px; background: #22c55e; color: #06240f; font-weight: 700; cursor: pointer; }}
    button:hover {{ background: #16a34a; color: #fff; }}
  </style>
</head>
<body>
  <main>
    {notice}
    <img id="liveView" src="/{LIVE_VIEW_FILENAME}?t={int(time.time())}" alt="Live camera preview" style="width: 100%; max-width: 960px; border-radius: 8px; border: 1px solid #cbd5e1; background: #fff; display: block; margin: 0 auto; transform: rotate(-90deg); transform-origin: center;" />
    <div class="update_status">
      <form id="updateForm" class="actions" method="post" action="{html.escape(update_endpoint)}">
        <button type="submit">Update</button>
      </form>
      <div class="status_text">
        <p>{html.escape(status_text)}</p>
        <p>{html.escape(commit_text)}</p>
      </div>
    </div>
  </main>
  <script>
    const imageElement = document.getElementById("liveView");
    const refreshIntervalMs = {CAPTURE_INTERVAL_SECONDS * 1000};
    setInterval(() => {{
      imageElement.src = "/{LIVE_VIEW_FILENAME}?t=" + Date.now();
    }}, refreshIntervalMs);

    const updateForm = document.getElementById("updateForm");
    if (updateForm) {{
      updateForm.addEventListener("submit", async (event) => {{
        event.preventDefault();

        try {{
          await fetch(updateForm.action, {{ method: "POST" }});
        }} finally {{
          setTimeout(() => {{
            window.location.reload();
          }}, 5000);
        }}
      }});
    }}
  </script>
</body>
</html>
"""
        return html_page.encode("utf-8")

    def perform_update_and_restart() -> None:
        time.sleep(0.5)
        update_repo(repo_root, remote_name=remote_name, main_branch=main_branch)
        _restart_process()

    class UpdaterRequestHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (http verb naming)
            if self.path == "/":
                page = render_page()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(page)))
                self.end_headers()
                self.wfile.write(page)
                return

            if self.path.startswith(f"/{LIVE_VIEW_FILENAME}"):
                if not live_view_path.exists():
                    self.send_error(HTTPStatus.NOT_FOUND, "Live view image not found yet")
                    return

                image = live_view_path.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
                self.send_header("Pragma", "no-cache")
                self.send_header("Expires", "0")
                self.send_header("Content-Length", str(len(image)))
                self.end_headers()
                self.wfile.write(image)
                return

            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

        def do_POST(self) -> None:  # noqa: N802 (http verb naming)
            if self.path != update_endpoint:
                self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
                return

            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", "/")
            self.end_headers()

            thread = threading.Thread(target=perform_update_and_restart, daemon=True)
            thread.start()

        def log_message(self, format_: str, *args: object) -> None:
            print(f"[web] {self.address_string()} - {format_ % args}")

    print(f"Starting server on http://{host}:{port}")
    capture_thread = threading.Thread(target=capture_live_view_forever, daemon=True)
    capture_thread.start()

    server = ThreadingHTTPServer((host, port), UpdaterRequestHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping server...")
    finally:
        capture_stop.set()
        capture_thread.join(timeout=1)
        server.server_close()
