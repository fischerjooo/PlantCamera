from __future__ import annotations

import subprocess
from pathlib import Path


def capture_photo(output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["termux-camera-photo", str(output_path)], check=True, capture_output=True, text=False)
