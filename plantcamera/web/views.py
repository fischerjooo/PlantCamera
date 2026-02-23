from __future__ import annotations

import html
import time
from pathlib import Path
from string import Template
from urllib.parse import quote

TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "dashboard.html"


def _nav_class(active_page: str, page: str) -> str:
    return "active" if active_page == page else ""


def render_dashboard(
    *,
    update_endpoint: str,
    repo_branch_text: str,
    repo_commit_text: str,
    status: dict[str, str | int | float | None],
    videos: list[str],
    logs: list[str],
    notice: str | None,
    active_page: str,
) -> bytes:
    template = Template(TEMPLATE_PATH.read_text(encoding="utf-8"))
    safe_notice = f"<p class='notice'>{html.escape(notice)}</p>" if notice else ""

    rows = "".join(
        "<tr>"
        f"<td>{html.escape(v)}</td>"
        "<td><div class='actions'>"
        f"<a class='btn watch-btn' href='/videos/{quote(v)}'>Watch</a>"
        f"<a class='btn download-btn' href='/download/{quote(v)}'>Download</a>"
        f"<form method='post' action='/delete/{quote(v)}'><button type='submit' class='danger'>Delete</button></form>"
        "</div></td>"
        "</tr>"
        for v in videos
    )
    videos_section = "<table><thead><tr><th>File</th><th>Actions</th></tr></thead><tbody>" + rows + "</tbody></table>" if rows else "<p class='meta'>No videos generated yet.</p>"

    live_section = ""
    timelapse_section = ""
    config_section = ""
    application_section = ""

    if active_page == "Live":
        live_section = """
        <section>
          <h2>Live View</h2>
          <img id='liveView' src='/live.jpg?t=$now' alt='Live camera preview' />
          $live_view_error
          <p class='meta'>Live view path: DCIM/PlantCamera/live_view.jpg</p>
          <p class='meta'>Last successful timelapse capture: <span class='ok'>$last_capture</span></p>
          $capture_error
          $encode_error
        </section>
        """

    if active_page == "TimeLapse":
        timelapse_section = """
        <section>
          <h2>Time lapse Management</h2>
          <p class='meta'>Images captured: $collected_images</p>
          <p class='meta'>Capture interval: $capture_interval_minutes minutes</p>
          <p class='meta'>Session duration (image count): $session_image_count images</p>
          <form method='post' action='/capture-now'><button type='submit'>Take timelapse photo now</button></form>
          <form method='post' action='/delete-all-images'><button type='submit' class='danger'>Delete all timelapse images</button></form>
        </section>

        <section>
          <h2>Video Management</h2>
          <div class='toolbar'>
            <form method='post' action='/convert-now'><button type='submit'>Convert</button></form>
            <form method='post' action='/merge-videos'><button type='submit'>Merge videos</button></form>
          </div>
          $videos_section
        </section>
        """

    if active_page == "Config":
        config_section = """
        <section>
          <h2>Config</h2>
          <form class='config-form' method='post' action='/config/save'>
            <label for='captureInterval'>Capture interval (seconds)</label>
            <input id='captureInterval' name='capture_interval_seconds' type='number' min='1' value='$capture_interval_seconds' required />

            <label for='rotationDegrees'>Image rotation degree</label>
            <select id='rotationDegrees' name='rotation_degrees'>
              <option value='0' $rotation_0>0</option>
              <option value='90' $rotation_90>90</option>
              <option value='180' $rotation_180>180</option>
              <option value='270' $rotation_270>270</option>
            </select>

            <label for='sessionImageCount'>Time lapse duration image count</label>
            <input id='sessionImageCount' name='session_image_count' type='number' min='1' value='$session_image_count' required />

            <label for='blackDetection'>Black detection percentage</label>
            <input id='blackDetection' name='black_detection_percentage' type='number' min='0' max='100' step='0.1' value='$black_detection_percentage' required />

            <button type='submit'>Save</button>
          </form>
          <p class='meta'>Config path: config.json (inside media directory)</p>
        </section>
        """

    if active_page == "App":
        application_section = """
        <section>
          <h2>Application</h2>
          <div class='toolbar'>
            <form method='post' action='$update_endpoint'><button type='submit'>Update</button></form>
            <div><p class='meta'>$repo_branch</p><p class='meta'>$repo_commit</p></div>
          </div>
          <h3>Logs (last 100)</h3>
          <div class='logs'>$log_lines</div>
        </section>
        """

    body = template.safe_substitute(
        notice=safe_notice,
        live_nav_class=_nav_class(active_page, "Live"),
        timelapse_nav_class=_nav_class(active_page, "TimeLapse"),
        config_nav_class=_nav_class(active_page, "Config"),
        app_nav_class=_nav_class(active_page, "App"),
        live_section=Template(live_section).safe_substitute(
            now=str(int(time.time())),
            live_view_error=(f"<p class='meta error'>Live view error: {html.escape(str(status['last_live_view_error']))}</p>" if status["last_live_view_error"] else ""),
            last_capture=html.escape(str(status["last_capture_timestamp"])),
            capture_error=(f"<p class='meta error'>Last timelapse capture error: {html.escape(str(status['last_capture_error']))}</p>" if status["last_capture_error"] else ""),
            encode_error=(f"<p class='meta error'>Last encode error: {html.escape(str(status['last_encode_error']))}</p>" if status["last_encode_error"] else ""),
        ),
        timelapse_section=Template(timelapse_section).safe_substitute(
            collected_images=str(status["collected_images"]),
            capture_interval_minutes=str(status["capture_interval_minutes"]),
            session_image_count=str(status["session_image_count"]),
            videos_section=videos_section,
        ),
        config_section=Template(config_section).safe_substitute(
            capture_interval_seconds=str(status["capture_interval_seconds"]),
            session_image_count=str(status["session_image_count"]),
            black_detection_percentage=str(status["black_detection_percentage"]),
            rotation_0=("selected" if int(status["rotation_degrees"]) == 0 else ""),
            rotation_90=("selected" if int(status["rotation_degrees"]) == 90 else ""),
            rotation_180=("selected" if int(status["rotation_degrees"]) == 180 else ""),
            rotation_270=("selected" if int(status["rotation_degrees"]) == 270 else ""),
        ),
        application_section=Template(application_section).safe_substitute(
            update_endpoint=html.escape(update_endpoint),
            repo_branch=html.escape(repo_branch_text),
            repo_commit=html.escape(repo_commit_text),
            log_lines="\n".join(html.escape(line) for line in logs) or "No logs yet.",
        ),
    )
    return body.encode("utf-8")
