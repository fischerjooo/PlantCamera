from __future__ import annotations

import html
import time
from pathlib import Path
from string import Template
from urllib.parse import quote

TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "dashboard.html"


def render_dashboard(*, update_endpoint: str, repo_branch_text: str, repo_commit_text: str, status: dict[str, str | int | None], videos: list[str], logs: list[str], notice: str | None) -> bytes:
    template = Template(TEMPLATE_PATH.read_text(encoding="utf-8"))
    safe_notice = f"<p class='notice'>{html.escape(notice)}</p>" if notice else ""
    rows = "".join(
        f"<tr><td>{html.escape(v)}</td><td><div class='actions'><a href='/videos/{quote(v)}'>Watch</a><a href='/download/{quote(v)}'>Download</a><form method='post' action='/delete/{quote(v)}'><button type='submit' class='danger'>Delete</button></form></div></td></tr>"
        for v in videos
    )
    videos_section = "<table><thead><tr><th>File</th><th>Actions</th></tr></thead><tbody>" + rows + "</tbody></table>" if rows else "<p class='meta'>No videos generated yet.</p>"
    body = template.safe_substitute(
        notice=safe_notice,
        now=str(int(time.time())),
        repo_branch=html.escape(repo_branch_text),
        repo_commit=html.escape(repo_commit_text),
        live_view_error=(f"<p class='meta error'>Live view error: {html.escape(str(status['last_live_view_error']))}</p>" if status["last_live_view_error"] else ""),
        capture_error=(f"<p class='meta error'>Last timelapse capture error: {html.escape(str(status['last_capture_error']))}</p>" if status["last_capture_error"] else ""),
        encode_error=(f"<p class='meta error'>Last encode error: {html.escape(str(status['last_encode_error']))}</p>" if status["last_encode_error"] else ""),
        last_capture=html.escape(str(status["last_capture_timestamp"])),
        collected_images=str(status["collected_images"]),
        capture_interval_minutes=str(status["capture_interval_minutes"]),
        session_image_count=str(status["session_image_count"]),
        videos_section=videos_section,
        update_endpoint=html.escape(update_endpoint),
        log_lines="\n".join(html.escape(line) for line in logs) or "No logs yet.",
    )
    return body.encode("utf-8")
