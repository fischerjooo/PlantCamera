from pathlib import Path

import pytest

from plantcamera.services.media import MediaService


def test_filename_safety_rejects_traversal(tmp_path: Path):
    service = MediaService(tmp_path)
    with pytest.raises(ValueError):
        service.get_video_path("../evil.mp4")


def test_video_listing_sorted_desc(tmp_path: Path):
    service = MediaService(tmp_path)
    (tmp_path / "a.mp4").write_bytes(b"x")
    (tmp_path / "z.mp4").write_bytes(b"x")
    assert service.list_videos() == ["z.mp4", "a.mp4"]
