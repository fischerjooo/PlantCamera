from __future__ import annotations

import subprocess
from pathlib import Path


class GitCommandError(RuntimeError):
    pass


def run_git(repo_path: Path, args: list[str]) -> str:
    try:
        proc = subprocess.run(["git", *args], cwd=repo_path, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as error:
        raise GitCommandError((error.stderr or "").strip() or "git command failed") from error
    return proc.stdout.strip()
