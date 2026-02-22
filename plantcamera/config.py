from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    host: str = "0.0.0.0"
    port: int = 8000
    media_base_dir: Path = Path("/sdcard/DCIM/PlantCamera")
    capture_interval_seconds: int = 15 * 60
    session_image_count: int = 48
    live_view_interval_seconds: int = 5
    timelapse_fps: int = 24
    timelapse_codec: str = "libx264"
    update_remote: str = "origin"
    update_branch: str = "main"
    update_endpoint: str = "/update"


def load_config(argv: list[str] | None = None) -> AppConfig:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--host", default=os.getenv("PLANTCAMERA_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PLANTCAMERA_PORT", "8000")))
    parser.add_argument(
        "--media-base-dir",
        default=os.getenv("PLANTCAMERA_MEDIA_DIR", "/sdcard/DCIM/PlantCamera"),
    )
    parser.add_argument(
        "--capture-interval-seconds",
        type=int,
        default=int(os.getenv("PLANTCAMERA_CAPTURE_INTERVAL_SECONDS", str(15 * 60))),
    )
    parser.add_argument(
        "--session-image-count",
        type=int,
        default=int(os.getenv("PLANTCAMERA_SESSION_IMAGE_COUNT", "48")),
    )
    parser.add_argument(
        "--timelapse-fps",
        type=int,
        default=int(os.getenv("PLANTCAMERA_OUTPUT_FPS", "24")),
    )
    parser.add_argument("--timelapse-codec", default=os.getenv("PLANTCAMERA_VIDEO_CODEC", "libx264"))
    parser.add_argument("--update-remote", default=os.getenv("PLANTCAMERA_UPDATE_REMOTE", "origin"))
    parser.add_argument("--update-branch", default=os.getenv("PLANTCAMERA_UPDATE_BRANCH", "main"))
    parser.add_argument("--update-endpoint", default=os.getenv("PLANTCAMERA_UPDATE_ENDPOINT", "/update"))

    args = parser.parse_args(argv)
    return AppConfig(
        host=args.host,
        port=args.port,
        media_base_dir=Path(args.media_base_dir),
        capture_interval_seconds=args.capture_interval_seconds,
        session_image_count=args.session_image_count,
        timelapse_fps=args.timelapse_fps,
        timelapse_codec=args.timelapse_codec,
        update_remote=args.update_remote,
        update_branch=args.update_branch,
        update_endpoint=args.update_endpoint,
    )
