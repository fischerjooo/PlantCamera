from __future__ import annotations

import shutil
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

CAPTURE_INTERVAL_SECONDS = 30 * 60
SESSION_DURATION_SECONDS = 24 * 60 * 60
OUTPUT_FPS = 24
VIDEO_CODEC = "libx264"

FRAME_PREFIX = "frame_"
VIDEO_PREFIX = "timelapse_"
TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"


@dataclass
class CaptureStatus:
    last_capture_timestamp: Optional[datetime] = None
    last_capture_error: Optional[str] = None
    last_encode_error: Optional[str] = None


class TimeLapseManager:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self.frames_dir = repo_root / "frames_current"
        self.videos_dir = repo_root / "videos"
        self.live_image_path = repo_root / "live.jpg"

        self.capture_interval = timedelta(seconds=CAPTURE_INTERVAL_SECONDS)
        self.session_duration = timedelta(seconds=SESSION_DURATION_SECONDS)
        self.output_fps = OUTPUT_FPS
        self.video_codec = VIDEO_CODEC

        self.frames_dir.mkdir(parents=True, exist_ok=True)
        self.videos_dir.mkdir(parents=True, exist_ok=True)

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._capture_status = CaptureStatus()
        self._capture_thread: Optional[threading.Thread] = None
        self._session_thread: Optional[threading.Thread] = None

        self.session_start = self._load_session_start()
        self.next_capture_due = datetime.now()

    def _load_session_start(self) -> datetime:
        latest_video_end: Optional[datetime] = None
        for video_path in sorted(self.videos_dir.glob(f"{VIDEO_PREFIX}*.mp4")):
            parsed = self._parse_video_range(video_path.stem)
            if parsed:
                _, end = parsed
                latest_video_end = end

        return latest_video_end or datetime.now()

    def _parse_video_range(self, stem: str) -> Optional[tuple[datetime, datetime]]:
        if not stem.startswith(VIDEO_PREFIX):
            return None

        suffix = stem[len(VIDEO_PREFIX) :]
        pieces = suffix.split("_")
        if len(pieces) != 4:
            return None

        start_raw = f"{pieces[0]}_{pieces[1]}"
        end_raw = f"{pieces[2]}_{pieces[3]}"

        try:
            start = datetime.strptime(start_raw, TIMESTAMP_FORMAT)
            end = datetime.strptime(end_raw, TIMESTAMP_FORMAT)
        except ValueError:
            return None

        return start, end

    def start(self) -> None:
        self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._session_thread = threading.Thread(target=self._session_loop, daemon=True)
        self._capture_thread.start()
        self._session_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._capture_thread is not None:
            self._capture_thread.join(timeout=1)
        if self._session_thread is not None:
            self._session_thread.join(timeout=1)

    def _capture_loop(self) -> None:
        while not self._stop_event.is_set():
            now = datetime.now()
            if now >= self.next_capture_due:
                self._capture_frame(now)
                self.next_capture_due = now + self.capture_interval

            self._stop_event.wait(1)

    def _capture_frame(self, timestamp: datetime) -> None:
        frame_name = f"{FRAME_PREFIX}{timestamp.strftime(TIMESTAMP_FORMAT)}.jpg"
        frame_path = self.frames_dir / frame_name

        try:
            subprocess.run(
                ["termux-camera-photo", str(frame_path)],
                check=True,
                capture_output=True,
                text=True,
            )
            shutil.copy2(frame_path, self.live_image_path)
            with self._lock:
                self._capture_status.last_capture_timestamp = timestamp
                self._capture_status.last_capture_error = None
        except FileNotFoundError:
            with self._lock:
                self._capture_status.last_capture_error = "termux-camera-photo not found"
        except subprocess.CalledProcessError as error:
            stderr = error.stderr.strip() if error.stderr else "unknown camera capture error"
            with self._lock:
                self._capture_status.last_capture_error = stderr

    def _session_loop(self) -> None:
        while not self._stop_event.is_set():
            if datetime.now() - self.session_start >= self.session_duration:
                self._encode_session()

            self._stop_event.wait(5)

    def _encode_session(self) -> None:
        frames = sorted(self.frames_dir.glob(f"{FRAME_PREFIX}*.jpg"))
        if not frames:
            return

        session_end = datetime.now()
        output_name = (
            f"{VIDEO_PREFIX}{self.session_start.strftime(TIMESTAMP_FORMAT)}_"
            f"{session_end.strftime(TIMESTAMP_FORMAT)}.mp4"
        )
        output_path = self.videos_dir / output_name

        ffmpeg_cmd = [
            "ffmpeg",
            "-y",
            "-framerate",
            str(self.output_fps),
            "-pattern_type",
            "glob",
            "-i",
            str(self.frames_dir / f"{FRAME_PREFIX}*.jpg"),
            "-c:v",
            self.video_codec,
            "-pix_fmt",
            "yuv420p",
            str(output_path),
        ]

        try:
            subprocess.run(ffmpeg_cmd, check=True, capture_output=True, text=True)
        except (FileNotFoundError, subprocess.CalledProcessError) as error:
            message = str(error)
            if isinstance(error, subprocess.CalledProcessError) and error.stderr:
                message = error.stderr.strip()
            with self._lock:
                self._capture_status.last_encode_error = message
            return

        for frame in frames:
            frame.unlink(missing_ok=True)

        with self._lock:
            self._capture_status.last_encode_error = None
        self.session_start = session_end

    def get_status(self) -> dict[str, str | int | float | None]:
        with self._lock:
            capture_ts = self._capture_status.last_capture_timestamp
            capture_error = self._capture_status.last_capture_error
            encode_error = self._capture_status.last_encode_error

        collected_images = len(list(self.frames_dir.glob(f"{FRAME_PREFIX}*.jpg")))
        now = datetime.now()
        session_elapsed = now - self.session_start
        configured_count = int(self.session_duration.total_seconds() // self.capture_interval.total_seconds())

        progress = min(100.0, (session_elapsed.total_seconds() / self.session_duration.total_seconds()) * 100)

        return {
            "last_capture_timestamp": capture_ts.strftime("%Y-%m-%d %H:%M:%S") if capture_ts else "Never",
            "last_capture_error": capture_error,
            "last_encode_error": encode_error,
            "session_start": self.session_start.strftime("%Y-%m-%d %H:%M:%S"),
            "session_end": (self.session_start + self.session_duration).strftime("%Y-%m-%d %H:%M:%S"),
            "session_progress_percent": round(progress, 2),
            "collected_images": collected_images,
            "configured_image_count": configured_count,
            "capture_interval_minutes": int(self.capture_interval.total_seconds() // 60),
            "session_duration_hours": int(self.session_duration.total_seconds() // 3600),
            "output_fps": self.output_fps,
            "video_codec": self.video_codec,
            "frames_dir": str(self.frames_dir),
            "videos_dir": str(self.videos_dir),
        }

    def list_videos(self) -> list[str]:
        return sorted((path.name for path in self.videos_dir.glob("*.mp4")), reverse=True)

    def get_video_path(self, filename: str) -> Path:
        if not filename.endswith(".mp4") or "/" in filename or ".." in filename:
            raise ValueError("invalid filename")

        path = self.videos_dir / filename
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(filename)

        return path

    def delete_video(self, filename: str) -> None:
        path = self.get_video_path(filename)
        path.unlink(missing_ok=True)
