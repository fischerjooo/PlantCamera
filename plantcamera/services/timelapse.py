from __future__ import annotations

import json
import re
import subprocess
import threading
import traceback
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from plantcamera.services.media import MediaService

TIMESTAMP_FORMAT = "%y%m%d_%H%M%S"
IMAGE_PREFIX = "image_"
VIDEO_PREFIX = "video_"
_VALID_IMAGE = re.compile(r"^[A-Za-z0-9._-]+\.jpg$")


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
        rotate_image_left: Callable[[Path], None],
        estimate_black_ratio: Callable[[Path], float | None],
        normalize_image_full_hd: Callable[[Path], None],
        encode_timelapse: Callable[[Path, Path, int, str], None],
        merge_videos: Callable[[list[Path], Path], None],
        list_encoders: Callable[[], set[str]],
        capture_interval_seconds: int,
        live_view_interval_seconds: int,
        session_image_count: int,
        fps: int,
        codec: str,
        logger: Callable[[str], None],
        config_path: Path | None = None,
        rotation_degrees: int = 90,
        black_detection_percentage: float = 90.0,
    ) -> None:
        self.base_media_dir = base_media_dir
        self.frames_dir = base_media_dir / "images"
        self.videos_dir = base_media_dir / "videos"
        self.live_image_path = base_media_dir / "live_view.jpg"
        self.capture_photo = capture_photo
        self.rotate_image_left = rotate_image_left
        self.estimate_black_ratio = estimate_black_ratio
        self.normalize_image_full_hd = normalize_image_full_hd
        self.encode_timelapse = encode_timelapse
        self.merge_videos = merge_videos
        self.list_encoders = list_encoders
        self.capture_interval = timedelta(seconds=max(1, int(capture_interval_seconds)))
        self.live_view_interval = timedelta(seconds=live_view_interval_seconds)
        self.session_image_count = max(1, int(session_image_count))
        self.output_fps = fps
        self.video_codec = codec
        self.logger = logger
        self.rotation_degrees = self._normalize_rotation_degrees(rotation_degrees)
        self.black_detection_threshold = self._normalize_black_percentage(black_detection_percentage) / 100.0
        self.config_path = config_path or (self.base_media_dir / "config.json")

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
        self._load_runtime_config()

    def _log(self, message: str) -> None:
        entry = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {message}"
        with self._lock:
            self._logs.append(entry)
        self.logger(message)

    def _normalize_rotation_degrees(self, value: int) -> int:
        if value not in {0, 90, 180, 270}:
            raise ValueError("Rotation must be one of: 0, 90, 180, 270.")
        return value

    def _normalize_black_percentage(self, value: float) -> float:
        percentage = float(value)
        if percentage < 0.0 or percentage > 100.0:
            raise ValueError("Black detection percentage must be between 0 and 100.")
        return percentage

    def _runtime_config_dict(self) -> dict[str, int | float]:
        return {
            "capture_interval_seconds": int(self.capture_interval.total_seconds()),
            "rotation_degrees": self.rotation_degrees,
            "session_image_count": self.session_image_count,
            "black_detection_percentage": round(self.black_detection_threshold * 100.0, 2),
        }

    def _load_runtime_config(self) -> None:
        if not self.config_path.exists():
            return
        try:
            loaded = json.loads(self.config_path.read_text(encoding="utf-8"))
            self._apply_runtime_config(
                capture_interval_seconds=int(loaded.get("capture_interval_seconds", int(self.capture_interval.total_seconds()))),
                rotation_degrees=int(loaded.get("rotation_degrees", self.rotation_degrees)),
                session_image_count=int(loaded.get("session_image_count", self.session_image_count)),
                black_detection_percentage=float(loaded.get("black_detection_percentage", self.black_detection_threshold * 100.0)),
            )
            self._log(f"Loaded runtime configuration from {self.config_path}")
        except Exception as error:
            self._log(f"Failed to load runtime configuration: {error}")

    def _save_runtime_config(self) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(json.dumps(self._runtime_config_dict(), indent=2), encoding="utf-8")

    def _apply_runtime_config(
        self,
        *,
        capture_interval_seconds: int,
        rotation_degrees: int,
        session_image_count: int,
        black_detection_percentage: float,
    ) -> None:
        capture_seconds = max(1, int(capture_interval_seconds))
        session_count = max(1, int(session_image_count))
        rotation = self._normalize_rotation_degrees(int(rotation_degrees))
        black_percentage = self._normalize_black_percentage(float(black_detection_percentage))

        self.capture_interval = timedelta(seconds=capture_seconds)
        self.next_capture_due = datetime.now() + self.capture_interval
        self.rotation_degrees = rotation
        self.session_image_count = session_count
        self.black_detection_threshold = black_percentage / 100.0

    def update_runtime_config(
        self,
        *,
        capture_interval_seconds: int,
        rotation_degrees: int,
        session_image_count: int,
        black_detection_percentage: float,
    ) -> tuple[bool, str]:
        with self._lock:
            try:
                self._apply_runtime_config(
                    capture_interval_seconds=capture_interval_seconds,
                    rotation_degrees=rotation_degrees,
                    session_image_count=session_image_count,
                    black_detection_percentage=black_detection_percentage,
                )
                self._save_runtime_config()
            except (TypeError, ValueError) as error:
                return False, str(error)
            except Exception as error:  # pragma: no cover - safety net
                return False, f"Failed to save config: {error}"

        self._log("Runtime configuration updated")
        return True, "Configuration saved."

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
        frame = self.frames_dir / f"{IMAGE_PREFIX}{timestamp.strftime(TIMESTAMP_FORMAT)}.jpg"
        error = self._take_photo(frame)
        discarded = False
        if not error:
            try:
                for _ in range(self.rotation_degrees // 90):
                    self.rotate_image_left(frame)
                self.normalize_image_full_hd(frame)
                black_ratio = self.estimate_black_ratio(frame)
                if black_ratio is not None and black_ratio > self.black_detection_threshold:
                    frame.unlink(missing_ok=True)
                    discarded = True
                    self._log(
                        f"Discarded image {frame.name} because black ratio is {black_ratio:.0%} "
                        f"(threshold: {self.black_detection_threshold:.0%})"
                    )
            except Exception as rotate_error:
                error = f"post-processing failed: {rotate_error}"
        with self._lock:
            if error:
                self._capture_status.last_capture_error = error
            else:
                self._capture_status.last_capture_error = None
                self._capture_status.last_capture_timestamp = timestamp
        if error:
            self._log(f"Timelapse capture error: {error}")
        elif not discarded:
            self._log(f"Captured timelapse image {frame.name}")

    def _capture_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                now = datetime.now()
                if now >= self.next_capture_due:
                    self._capture_frame(now)
                    self.next_capture_due = now + self.capture_interval
                self._stop_event.wait(1)
            except Exception as error:  # pragma: no cover - safety net
                message = f"Capture loop crashed: {error}"
                with self._lock:
                    self._capture_status.last_capture_error = message
                self._log(message)
                self._log(traceback.format_exc().strip())
                self._stop_event.wait(1)

    def _live_view_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                error = self._take_photo(self.live_image_path)
                with self._lock:
                    self._capture_status.last_live_view_error = error
                self._stop_event.wait(self.live_view_interval.total_seconds())
            except Exception as error:  # pragma: no cover - safety net
                message = f"Live view loop crashed: {error}"
                with self._lock:
                    self._capture_status.last_live_view_error = message
                self._log(message)
                self._log(traceback.format_exc().strip())
                self._stop_event.wait(1)

    def _collected_images(self) -> list[Path]:
        return sorted(self.frames_dir.glob(f"{IMAGE_PREFIX}*.jpg"))

    def _session_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                if len(self._collected_images()) >= self.session_image_count:
                    success, message = self._encode_session()
                    if not success:
                        self._log(f"Session encode error: {message}")
                self._stop_event.wait(5)
            except Exception as error:  # pragma: no cover - safety net
                message = f"Session loop crashed: {error}"
                with self._lock:
                    self._capture_status.last_encode_error = message
                self._log(message)
                self._log(traceback.format_exc().strip())
                self._stop_event.wait(1)

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
            images = self._collected_images()
            if not images:
                return False, "No collected images available for conversion."
            session_end = datetime.now()
            output_name = f"{VIDEO_PREFIX}{self.session_start.strftime(TIMESTAMP_FORMAT)}_{session_end.strftime(TIMESTAMP_FORMAT)}.mp4"
            output = self.videos_dir / output_name
            try:
                self.encode_timelapse(self.frames_dir / f"{IMAGE_PREFIX}*.jpg", output, self.output_fps, self._resolve_codec())
            except (FileNotFoundError, subprocess.CalledProcessError, RuntimeError) as error:
                message = str(error)
                if isinstance(error, subprocess.CalledProcessError):
                    message = (error.stderr or b"").decode("utf-8", errors="replace").strip() or message
                with self._lock:
                    self._capture_status.last_encode_error = message
                self._log(f"Encode failed: {message}")
                return False, message
            except Exception as error:  # pragma: no cover - safety net
                message = f"Unexpected encode error: {error}"
                with self._lock:
                    self._capture_status.last_encode_error = message
                self._log(message)
                self._log(traceback.format_exc().strip())
                return False, message
            for image in images:
                image.unlink(missing_ok=True)
            self.session_start = session_end
            with self._lock:
                self._capture_status.last_encode_error = None
            return True, f"Converted {len(images)} images into {output_name}."

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

    def trigger_merge_videos(self) -> tuple[bool, str]:
        with self._encode_lock:
            videos = sorted((p for p in self.videos_dir.glob("*.mp4") if p.is_file()), key=lambda p: p.name)
            if len(videos) < 2:
                return False, "Need at least 2 videos to merge."

            first_name = videos[0].stem
            last_name = videos[-1].stem
            output_name = f"merged_{first_name}_{last_name}.mp4"
            output = self.videos_dir / output_name

            try:
                self.merge_videos(videos, output)
            except (FileNotFoundError, subprocess.CalledProcessError, RuntimeError) as error:
                message = str(error)
                if isinstance(error, subprocess.CalledProcessError):
                    message = (error.stderr or b"").decode("utf-8", errors="replace").strip() or message
                with self._lock:
                    self._capture_status.last_encode_error = message
                self._log(f"Merge failed: {message}")
                return False, message

            for video in videos:
                video.unlink(missing_ok=True)
            with self._lock:
                self._capture_status.last_encode_error = None
            self._log(f"Merged {len(videos)} videos into {output_name}")
            return True, f"Merged {len(videos)} videos into {output_name}."

    def get_status(self) -> dict[str, str | int | float | None]:
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
            "capture_interval_seconds": int(self.capture_interval.total_seconds()),
            "rotation_degrees": self.rotation_degrees,
            "black_detection_percentage": round(self.black_detection_threshold * 100.0, 2),
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

    def validate_image_name(self, filename: str) -> None:
        if not _VALID_IMAGE.match(filename) or ".." in filename or "/" in filename or "\\" in filename:
            raise ValueError("invalid filename")

    def list_images(self) -> list[str]:
        return sorted((p.name for p in self.frames_dir.glob(f"{IMAGE_PREFIX}*.jpg") if p.is_file()), reverse=True)

    def get_image_path(self, name: str) -> Path:
        self.validate_image_name(name)
        path = self.frames_dir / name
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(name)
        return path

    def delete_image(self, name: str) -> None:
        image = self.get_image_path(name)
        image.unlink(missing_ok=True)
        self._log(f"Deleted image {name}")

    def delete_all_frames(self) -> int:
        deleted = 0
        for frame in self._collected_images():
            frame.unlink(missing_ok=True)
            deleted += 1
        self._log(f"Deleted {deleted} collected timelapse images")
        return deleted
