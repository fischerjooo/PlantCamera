from __future__ import annotations

import subprocess
from pathlib import Path


def list_encoders() -> set[str]:
    process = subprocess.run(["ffmpeg", "-encoders"], check=True, capture_output=True, text=True)
    encoders: set[str] = set()
    for line in process.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].startswith("V"):
            encoders.add(parts[1])
    return encoders


def encode_timelapse(image_glob: Path, output_file: Path, fps: int, codec: str) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-framerate",
            str(fps),
            "-pattern_type",
            "glob",
            "-i",
            str(image_glob),
            "-c:v",
            codec,
            "-pix_fmt",
            "yuv420p",
            str(output_file),
        ],
        check=True,
        capture_output=True,
        text=False,
    )
