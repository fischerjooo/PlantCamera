from __future__ import annotations

import subprocess
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

CAPTURE_INTERVAL_SECONDS = 30 * 60
LIVE_VIEW_INTERVAL_SECONDS = 5
SESSION_IMAGE_COUNT = 48
OUTPUT_FPS = 24
VIDEO_CODEC = "libx264"

FRAME_PREFIX = "frame_"
VIDEO_PREFIX = "timelapse_"
TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"


@dataclass
class CaptureStatus:
    last_capture_timestamp: Optional[datetime] = None
    last_capture_error: Optional[str] = None
    last_live_view_error: Optional[str] = None
    last_encode_error: Optional[str] = None


class TimeLapseManager:
    def __init__(self, repo_root: Path, log_callback: Optional[Callable[[str], None]] = None) -> None:
        self.repo_root = repo_root
        self.log_callback = log_callback

        self.base_media_dir = Path("/sdcard/DCIM/PlantCamera")
        self.frames_dir = self.base_media_dir / "images"
        self.videos_dir = self.base_media_dir / "videos"
        self.live_image_path = self.base_media_dir / "live_view.jpg"

        self.capture_interval = timedelta(seconds=CAPTURE_INTERVAL_SECONDS)
        self.live_view_interval = timedelta(seconds=LIVE_VIEW_INTERVAL_SECONDS)
        self.session_image_count = SESSION_IMAGE_COUNT
        self.output_fps = OUTPUT_FPS
        self.video_codec = VIDEO_CODEC

        self._lock = threading.Lock()
        self._camera_lock = threading.Lock()
        self._encode_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._capture_status = CaptureStatus()
        self._capture_thread: Optional[threading.Thread] = None
        self._live_view_thread: Optional[threading.Thread] = None
        self._session_thread: Optional[threading.Thread] = None
        self._logs: deque[str] = deque(maxlen=100)

        self._prepare_directories()

        self.session_start = self._load_session_start()
        self.next_capture_due = datetime.now()

    def _prepare_directories(self) -> None:
        try:
            self.base_media_dir.mkdir(parents=True, exist_ok=True)
            self.frames_dir.mkdir(parents=True, exist_ok=True)
            self.videos_dir.mkdir(parents=True, exist_ok=True)
            self._log(f"Media directories ready at {self.base_media_dir}")
        except OSError as error:
            fallback = self.repo_root / "DCIM" / "PlantCamera"
            self.base_media_dir = fallback
            self.frames_dir = fallback / "images"
            self.videos_dir = fallback / "videos"
            self.live_image_path = fallback / "live_view.jpg"
            self.base_media_dir.mkdir(parents=True, exist_ok=True)
            self.frames_dir.mkdir(parents=True, exist_ok=True)
            self.videos_dir.mkdir(parents=True, exist_ok=True)
            self._log(f"Failed to access /sdcard/DCIM/PlantCamera ({error}). Using fallback {fallback}")

    def _log(self, message: str) -> None:
        entry = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {message}"
        with self._lock:
            self._logs.append(entry)
        if self.log_callback is not None:
            self.log_callback(f"[timelapse] {message}")

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
        self._live_view_thread = threading.Thread(target=self._live_view_loop, daemon=True)
        self._session_thread = threading.Thread(target=self._session_loop, daemon=True)
        self._capture_thread.start()
        self._live_view_thread.start()
        self._session_thread.start()
        self._log("Timelapse manager started")

    def stop(self) -> None:
        self._stop_event.set()
        if self._capture_thread is not None:
            self._capture_thread.join(timeout=1)
        if self._live_view_thread is not None:
            self._live_view_thread.join(timeout=1)
        if self._session_thread is not None:
            self._session_thread.join(timeout=1)
        self._log("Timelapse manager stopped")

    def _take_photo(self, destination: Path) -> Optional[str]:
        try:
            with self._camera_lock:
                subprocess.run(
                    ["termux-camera-photo", str(destination)],
                    check=True,
                    capture_output=True,
                    text=True,
                )
            return None
        except FileNotFoundError:
            return "termux-camera-photo not found"
        except subprocess.CalledProcessError as error:
            return error.stderr.strip() if error.stderr else "unknown camera capture error"

    def _capture_loop(self) -> None:
        while not self._stop_event.is_set():
            now = datetime.now()
            if now >= self.next_capture_due:
                self._capture_frame(now)
                self.next_capture_due = now + self.capture_interval

            self._stop_event.wait(1)

    def _live_view_loop(self) -> None:
        last_error: Optional[str] = None
        while not self._stop_event.is_set():
            error = self._take_photo(self.live_image_path)
            with self._lock:
                self._capture_status.last_live_view_error = error

            if error != last_error and error is not None:
                self._log(f"Live view capture error: {error}")
            last_error = error
            self._stop_event.wait(self.live_view_interval.total_seconds())

    def _capture_frame(self, timestamp: datetime) -> None:
        frame_name = f"{FRAME_PREFIX}{timestamp.strftime(TIMESTAMP_FORMAT)}.jpg"
        frame_path = self.frames_dir / frame_name
        error = self._take_photo(frame_path)

        with self._lock:
            if error is None:
                self._capture_status.last_capture_timestamp = timestamp
                self._capture_status.last_capture_error = None
            else:
                self._capture_status.last_capture_error = error

        if error is None:
            self._log(f"Captured timelapse frame {frame_name}")
        else:
            self._log(f"Timelapse capture error: {error}")

    def trigger_capture_now(self) -> tuple[bool, str]:
        timestamp = datetime.now()
        self._capture_frame(timestamp)
        self.next_capture_due = timestamp + self.capture_interval

        with self._lock:
            error = self._capture_status.last_capture_error

        if error:
            return False, error
        return True, "Manual timelapse capture completed."

    def _session_loop(self) -> None:
        while not self._stop_event.is_set():
            if self._collected_image_count() >= self.session_image_count:
                self._encode_session()

            self._stop_event.wait(5)

    def _collected_image_count(self) -> int:
        return len(list(self.frames_dir.glob(f"{FRAME_PREFIX}*.jpg")))

    def _encode_session(self) -> tuple[bool, str]:
        with self._encode_lock:
            frames = sorted(self.frames_dir.glob(f"{FRAME_PREFIX}*.jpg"))
            if not frames:
                return False, "No collected images available for conversion."

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
                self._log(f"Encode error: {message}")
                return False, message

            for frame in frames:
                frame.unlink(missing_ok=True)

            with self._lock:
                self._capture_status.last_encode_error = None
            self.session_start = session_end
            self._log(f"Converted {len(frames)} images into {output_name}")
            return True, f"Converted {len(frames)} images into {output_name}."

    def trigger_convert_now(self) -> tuple[bool, str]:
        success, message = self._encode_session()
        if success:
            self.next_capture_due = datetime.now() + self.capture_interval
        return success, message

    def get_status(self) -> dict[str, str | int | float | None]:
        with self._lock:
            capture_ts = self._capture_status.last_capture_timestamp
            capture_error = self._capture_status.last_capture_error
            live_view_error = self._capture_status.last_live_view_error
            encode_error = self._capture_status.last_encode_error

        collected_images = self._collected_image_count()

        return {
            "last_capture_timestamp": capture_ts.strftime("%Y-%m-%d %H:%M:%S") if capture_ts else "Never",
            "last_capture_error": capture_error,
            "last_live_view_error": live_view_error,
            "last_encode_error": encode_error,
            "session_start": self.session_start.strftime("%Y-%m-%d %H:%M:%S"),
            "collected_images": collected_images,
            "session_image_count": self.session_image_count,
            "capture_interval_minutes": int(self.capture_interval.total_seconds() // 60),
        }

    def get_logs(self) -> list[str]:
        with self._lock:
            return list(self._logs)

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
        self._log(f"Deleted video {filename}")
