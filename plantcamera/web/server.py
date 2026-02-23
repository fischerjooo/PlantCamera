from __future__ import annotations

import threading
from collections import deque
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote

from plantcamera.web.routes import dispatch


class WebApplication:
    def __init__(self, config, timelapse, updater, test_mode: bool = False, camera_simulator=None) -> None:
        self.config = config
        self.timelapse = timelapse
        self.updater = updater
        self.test_mode = test_mode
        self.camera_simulator = camera_simulator
        self._logs: deque[str] = deque(maxlen=100)
        self.server: ThreadingHTTPServer | None = None

    def log(self, message: str) -> None:
        self._logs.append(message)

    def recent_logs(self) -> list[str]:
        return list(self._logs)

    def run_update_async(self) -> None:
        def _run() -> None:
            self.updater.update_repo()
            if not self.test_mode:
                self.updater.schedule_restart()

        threading.Thread(target=_run, daemon=True).start()

    def shutdown_async(self) -> None:
        if self.server is not None:
            threading.Thread(target=self.server.shutdown, daemon=True).start()


class RequestHandler(BaseHTTPRequestHandler):
    app: WebApplication

    def send_bytes(self, body: bytes, content_type: str) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.end_headers()

    def redirect_with_notice(self, ok: bool, message: str, *, page: str | None = None) -> None:
        prefix = "OK" if ok else "ERROR"
        page_part = f"page={quote(page)}&" if page else ""
        self.redirect(f"/?{page_part}notice={quote(f'{prefix}: {message}')}")

    def do_GET(self) -> None:  # noqa: N802
        dispatch(self, "GET", self.path)

    def do_POST(self) -> None:  # noqa: N802
        dispatch(self, "POST", self.path)

    def log_message(self, format_: str, *args: object) -> None:
        # Keep default request logs out of dashboard ring buffer.
        return


def run_server(app: WebApplication) -> None:
    app.timelapse.start()
    httpd = ThreadingHTTPServer((app.config.host, app.config.port), RequestHandler)
    RequestHandler.app = app
    app.server = httpd
    try:
        httpd.serve_forever()
    finally:
        app.timelapse.stop()
        httpd.server_close()
