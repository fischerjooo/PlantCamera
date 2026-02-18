from __future__ import annotations

import os
import sys


def restart_process() -> None:
    os.execv(sys.executable, [sys.executable, *sys.argv])
