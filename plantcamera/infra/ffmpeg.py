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
    temporary_output = output_file.with_suffix(".tmp.mp4")
    if temporary_output.exists():
        temporary_output.unlink(missing_ok=True)

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
            str(temporary_output),
        ],
        check=True,
        capture_output=True,
        text=False,
    )

    size = temporary_output.stat().st_size if temporary_output.exists() else 0
    # Tiny MP4 files usually indicate a failed or empty conversion even if ffmpeg returned 0.
    if size < 256:
        temporary_output.unlink(missing_ok=True)
        raise RuntimeError(
            f"Generated video file is too small ({size} bytes). "
            "Conversion likely failed; check ffmpeg installation, codec support, and captured frames."
        )

    temporary_output.replace(output_file)
