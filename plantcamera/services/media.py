from __future__ import annotations

import re
from pathlib import Path

_VALID_VIDEO = re.compile(r"^[A-Za-z0-9._-]+\.mp4$")


class MediaService:
    def __init__(self, videos_dir: Path) -> None:
        self.videos_dir = videos_dir
        self.videos_dir.mkdir(parents=True, exist_ok=True)

    def validate_video_name(self, filename: str) -> None:
        if not _VALID_VIDEO.match(filename) or ".." in filename or "/" in filename or "\\" in filename:
            raise ValueError("invalid filename")

    def list_videos(self) -> list[str]:
        return sorted((p.name for p in self.videos_dir.glob("*.mp4") if p.is_file()), reverse=True)

    def get_video_path(self, filename: str) -> Path:
        self.validate_video_name(filename)
        path = self.videos_dir / filename
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(filename)
        return path

    def delete_video(self, filename: str) -> None:
        path = self.get_video_path(filename)
        path.unlink(missing_ok=True)
