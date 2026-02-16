from __future__ import annotations

import html
import os
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from src.git_updater import GitCommandError, get_repo_status, update_repo


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
    def render_page(message: str | None = None) -> bytes:
        try:
            status = get_repo_status(repo_root)
            title = f"Branch: {status.branch}"
            subtitle = f"Last commit: {status.last_commit_date}"
        except GitCommandError as error:
            title = "Branch: unknown"
            subtitle = f"Git error: {error}"

        notice = f"<p class='notice'>{html.escape(message)}</p>" if message else ""

        html_page = f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>PlantCamera Updater</title>
  <style>
    body {{ font-family: sans-serif; margin: 0; background: #f2f4f8; color: #202124; }}
    header {{ display: flex; justify-content: space-between; align-items: center; padding: 16px; background: #0f766e; color: #fff; }}
    h1 {{ font-size: 1.1rem; margin: 0; }}
    p {{ margin: 4px 0 0; }}
    main {{ padding: 20px; }}
    button {{ border: none; padding: 10px 16px; border-radius: 6px; background: #22c55e; color: #06240f; font-weight: 700; cursor: pointer; }}
    button:hover {{ background: #16a34a; color: #fff; }}
    .notice {{ background: #dbeafe; border: 1px solid #93c5fd; padding: 10px; border-radius: 6px; }}
  </style>
</head>
<body>
  <header>
    <div>
      <h1>{html.escape(title)}</h1>
      <p>{html.escape(subtitle)}</p>
    </div>
    <form method=\"post\" action=\"{html.escape(update_endpoint)}\">
      <button type=\"submit\">Update</button>
    </form>
  </header>
  <main>
    {notice}
    <p>Use the update button to fetch the latest changes and restart the app.</p>
  </main>
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
            if self.path != "/":
                self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
                return

            page = render_page()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)

        def do_POST(self) -> None:  # noqa: N802 (http verb naming)
            if self.path != update_endpoint:
                self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
                return

            page = render_page("Update started. The server will restart shortly.")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)

            thread = threading.Thread(target=perform_update_and_restart, daemon=True)
            thread.start()

        def log_message(self, format_: str, *args: object) -> None:
            print(f"[web] {self.address_string()} - {format_ % args}")

    print(f"Starting server on http://{host}:{port}")
    server = ThreadingHTTPServer((host, port), UpdaterRequestHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping server...")
    finally:
        server.server_close()
