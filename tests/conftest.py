from __future__ import annotations

import os
import socket
import sys
import threading
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.webapp import run_web_server


@pytest.fixture
def server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    media_dir = tmp_path / "media"
    bin_dir = tmp_path / "bin"
    media_dir.mkdir(parents=True, exist_ok=True)
    bin_dir.mkdir(parents=True, exist_ok=True)

    termux_camera = bin_dir / "termux-camera-photo"
    termux_camera.write_text(
        "#!/usr/bin/env python3\n"
        "from pathlib import Path\n"
        "import sys\n"
        "out = Path(sys.argv[1])\n"
        "out.parent.mkdir(parents=True, exist_ok=True)\n"
        "out.write_bytes(b'\\xff\\xd8\\xff\\xd9')\n"
    )
    termux_camera.chmod(0o755)

    ffmpeg = bin_dir / "ffmpeg"
    ffmpeg.write_text(
        "#!/usr/bin/env python3\n"
        "from pathlib import Path\n"
        "import sys\n"
        "if '-encoders' in sys.argv:\n"
        "    print(' V..... libx264 libx264 encoder')\n"
        "    print(' V..... mpeg4 mpeg4 encoder')\n"
        "    raise SystemExit(0)\n"
        "output = Path(sys.argv[-1])\n"
        "output.parent.mkdir(parents=True, exist_ok=True)\n"
        "output.write_bytes(b'FAKE-MP4')\n"
    )
    ffmpeg.chmod(0o755)

    monkeypatch.setenv("PLANTCAMERA_MEDIA_DIR", str(media_dir))
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ.get('PATH', '')}")

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    thread = threading.Thread(
        target=run_web_server,
        kwargs={
            "host": "127.0.0.1",
            "port": port,
            "repo_root": ROOT,
            "remote_name": "origin",
            "main_branch": "main",
            "update_endpoint": "/update",
            "test_mode": True,
        },
        daemon=True,
    )
    thread.start()

    base_url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            with urlopen(f"{base_url}/__health", timeout=0.5) as response:
                if response.status == 200:
                    break
        except Exception:
            time.sleep(0.1)
    else:
        raise RuntimeError("server did not start")

    yield {"base_url": base_url, "media_dir": media_dir}

    try:
        req = Request(f"{base_url}/__shutdown", method="POST")
        urlopen(req, timeout=2).read()
    except HTTPError:
        pass
    thread.join(timeout=5)
