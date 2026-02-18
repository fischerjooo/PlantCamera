from __future__ import annotations

from pathlib import Path

from plantcamera.app import run


if __name__ == "__main__":
    run(repo_root=Path(__file__).resolve().parents[1])
