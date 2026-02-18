from __future__ import annotations

import subprocess
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from plantcamera.services.media import MediaService

TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"
FRAME_PREFIX = "frame_"
VIDEO_PREFIX = "timelapse_"


@dataclass
class CaptureStatus:
    last_capture_timestamp: datetime | None = None
    last_capture_error: str | None = None
    last_live_view_error: str | None = None
    last_encode_error: str | None = None


class TimelapseService:
    def __init__(
        self,
        base_media_dir: Path,
        capture_photo: Callable[[Path], None],
        encode_timelapse: Callable[[Path, Path, int, str], None],
        list_encoders: Callable[[], set[str]],
        capture_interval_seconds: int,
        live_view_interval_seconds: int,
        session_image_count: int,
        fps: int,
        codec: str,
        logger: Callable[[str], None],
    ) -> None:
        self.base_media_dir = base_media_dir
        self.frames_dir = base_media_dir / "images"
        self.videos_dir = base_media_dir / "videos"
        self.live_image_path = base_media_dir / "live_view.jpg"
        self.capture_photo = capture_photo
        self.encode_timelapse = encode_timelapse
        self.list_encoders = list_encoders
        self.capture_interval = timedelta(seconds=capture_interval_seconds)
        self.live_view_interval = timedelta(seconds=live_view_interval_seconds)
        self.session_image_count = session_image_count
        self.output_fps = fps
        self.video_codec = codec
        self.logger = logger

        self._lock = threading.Lock()
        self._camera_lock = threading.Lock()
        self._encode_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._capture_status = CaptureStatus()
        self._capture_thread: threading.Thread | None = None
        self._live_thread: threading.Thread | None = None
        self._session_thread: threading.Thread | None = None
        self._logs: deque[str] = deque(maxlen=100)

        self.base_media_dir.mkdir(parents=True, exist_ok=True)
        self.frames_dir.mkdir(parents=True, exist_ok=True)
        self.videos_dir.mkdir(parents=True, exist_ok=True)

        self.media = MediaService(self.videos_dir)
        self.session_start = datetime.now()
        self.next_capture_due = datetime.now() + self.capture_interval

    def _log(self, message: str) -> None:
        entry = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {message}"
        with self._lock:
            self._logs.append(entry)
        self.logger(message)

    def start(self) -> None:
        self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._live_thread = threading.Thread(target=self._live_view_loop, daemon=True)
        self._session_thread = threading.Thread(target=self._session_loop, daemon=True)
        self._capture_thread.start()
        self._live_thread.start()
        self._session_thread.start()
        self._log("Timelapse service started")

    def stop(self) -> None:
        self._stop_event.set()
        for thread in (self._capture_thread, self._live_thread, self._session_thread):
            if thread is not None:
                thread.join(timeout=1)

    def _take_photo(self, path: Path) -> str | None:
        try:
            with self._camera_lock:
                self.capture_photo(path)
            return None
        except FileNotFoundError:
            return "termux-camera-photo not found"
        except subprocess.CalledProcessError as error:
            return (error.stderr or b"").decode("utf-8", errors="replace").strip() or "capture failed"

    def _capture_frame(self, timestamp: datetime) -> None:
        frame = self.frames_dir / f"{FRAME_PREFIX}{timestamp.strftime(TIMESTAMP_FORMAT)}.jpg"
        error = self._take_photo(frame)
        with self._lock:
            if error:
                self._capture_status.last_capture_error = error
            else:
                self._capture_status.last_capture_error = None
                self._capture_status.last_capture_timestamp = timestamp
        self._log(f"Captured timelapse frame {frame.name}" if not error else f"Timelapse capture error: {error}")

    def _capture_loop(self) -> None:
        while not self._stop_event.is_set():
            now = datetime.now()
            if now >= self.next_capture_due:
                self._capture_frame(now)
                self.next_capture_due = now + self.capture_interval
            self._stop_event.wait(1)

    def _live_view_loop(self) -> None:
        while not self._stop_event.is_set():
            error = self._take_photo(self.live_image_path)
            with self._lock:
                self._capture_status.last_live_view_error = error
            self._stop_event.wait(self.live_view_interval.total_seconds())

    def _collected_images(self) -> list[Path]:
        return sorted(self.frames_dir.glob(f"{FRAME_PREFIX}*.jpg"))

    def _session_loop(self) -> None:
        while not self._stop_event.is_set():
            if len(self._collected_images()) >= self.session_image_count:
                self._encode_session()
            self._stop_event.wait(5)

    def _resolve_codec(self) -> str:
        try:
            encoders = self.list_encoders()
        except Exception:
            encoders = set()
        if self.video_codec in encoders:
            return self.video_codec
        if "mpeg4" in encoders:
            return "mpeg4"
        return self.video_codec

    def _encode_session(self) -> tuple[bool, str]:
        with self._encode_lock:
            frames = self._collected_images()
            if not frames:
                return False, "No collected images available for conversion."
            session_end = datetime.now()
            output_name = f"{VIDEO_PREFIX}{self.session_start.strftime(TIMESTAMP_FORMAT)}_{session_end.strftime(TIMESTAMP_FORMAT)}.mp4"
            output = self.videos_dir / output_name
            try:
                self.encode_timelapse(self.frames_dir / f"{FRAME_PREFIX}*.jpg", output, self.output_fps, self._resolve_codec())
            except (FileNotFoundError, subprocess.CalledProcessError) as error:
                message = str(error)
                if isinstance(error, subprocess.CalledProcessError):
                    message = (error.stderr or b"").decode("utf-8", errors="replace").strip() or message
                with self._lock:
                    self._capture_status.last_encode_error = message
                return False, message
            for frame in frames:
                frame.unlink(missing_ok=True)
            self.session_start = session_end
            with self._lock:
                self._capture_status.last_encode_error = None
            return True, f"Converted {len(frames)} images into {output_name}."

    def trigger_capture_now(self) -> tuple[bool, str]:
        now = datetime.now()
        self._capture_frame(now)
        self.next_capture_due = now + self.capture_interval
        with self._lock:
            if self._capture_status.last_capture_error:
                return False, self._capture_status.last_capture_error
        return True, "Manual timelapse capture completed."

    def trigger_convert_now(self) -> tuple[bool, str]:
        success, message = self._encode_session()
        if success:
            self.next_capture_due = datetime.now() + self.capture_interval
        return success, message

    def get_status(self) -> dict[str, str | int | None]:
        with self._lock:
            cap = self._capture_status
        return {
            "last_capture_timestamp": cap.last_capture_timestamp.strftime("%Y-%m-%d %H:%M:%S") if cap.last_capture_timestamp else "Never",
            "last_capture_error": cap.last_capture_error,
            "last_live_view_error": cap.last_live_view_error,
            "last_encode_error": cap.last_encode_error,
            "collected_images": len(self._collected_images()),
            "session_image_count": self.session_image_count,
            "capture_interval_minutes": int(self.capture_interval.total_seconds() // 60),
        }

    def get_logs(self) -> list[str]:
        with self._lock:
            return list(self._logs)

    def list_videos(self) -> list[str]:
        return self.media.list_videos()

    def get_video_path(self, name: str) -> Path:
        return self.media.get_video_path(name)

    def delete_video(self, name: str) -> None:
        self.media.delete_video(name)
        self._log(f"Deleted video {name}")
