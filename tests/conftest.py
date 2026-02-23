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


def _start_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ffmpeg_payload: bytes, *, media_dir: Path | None = None):
    media_dir = media_dir or (tmp_path / "media")
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
        "if '-f' in sys.argv and 'concat' in sys.argv:\n"
        "    list_file = Path(sys.argv[sys.argv.index('-i') + 1])\n"
        "    items = []\n"
        "    for line in list_file.read_text(encoding='utf-8').splitlines():\n"
        "        if line.startswith(\"file '\") and line.endswith(\"'\"):\n"
        "            items.append(Path(line[6:-1]).name)\n"
        "    payload = ('MERGED:' + '|'.join(items)).encode('utf-8') * 30\n"
        "    output.write_bytes(payload)\n"
        "else:\n"
        f"    output.write_bytes({ffmpeg_payload!r})\n"
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

    return {"base_url": base_url, "media_dir": media_dir, "thread": thread}


def _stop_server(base_url: str, thread: threading.Thread) -> None:
    try:
        req = Request(f"{base_url}/__shutdown", method="POST")
        urlopen(req, timeout=2).read()
    except HTTPError:
        pass
    thread.join(timeout=5)


@pytest.fixture
def server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    info = _start_server(tmp_path, monkeypatch, b"FAKE-MP4" * 40)
    yield {"base_url": info["base_url"], "media_dir": info["media_dir"]}
    _stop_server(info["base_url"], info["thread"])


@pytest.fixture
def server_with_tiny_video(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    info = _start_server(tmp_path, monkeypatch, b"0" * 48)
    yield {"base_url": info["base_url"], "media_dir": info["media_dir"]}
    _stop_server(info["base_url"], info["thread"])


@pytest.fixture
def restartable_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    state: dict[str, object] = {}

    def _start():
        info = _start_server(tmp_path, monkeypatch, b"FAKE-MP4" * 40, media_dir=state.get("media_dir"))
        state["base_url"] = info["base_url"]
        state["media_dir"] = info["media_dir"]
        state["thread"] = info["thread"]

    def _restart() -> dict[str, object]:
        _stop_server(state["base_url"], state["thread"])
        _start()
        return {"base_url": state["base_url"], "media_dir": state["media_dir"]}

    _start()
    result = {"base_url": state["base_url"], "media_dir": state["media_dir"], "restart": _restart}
    yield result
    _stop_server(state["base_url"], state["thread"])
