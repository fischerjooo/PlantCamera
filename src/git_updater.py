from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class RepoStatus:
    branch: str
    last_commit_date: str


class GitCommandError(RuntimeError):
    """Raised when a git command fails."""


def _run_git(args: Iterable[str], repo_path: Path) -> str:
    process = subprocess.run(
        ["git", *args],
        cwd=repo_path,
        check=False,
        capture_output=True,
        text=True,
    )
    if process.returncode != 0:
        raise GitCommandError(process.stderr.strip() or process.stdout.strip())
    return process.stdout.strip()


def _candidate_branches(repo_path: Path, main_branch: str) -> list[str]:
    remote_raw = _run_git(["branch", "-r", "--format=%(refname:short)"], repo_path)
    local_raw = _run_git(["branch", "--format=%(refname:short)"], repo_path)

    candidates: list[str] = []

    for branch in remote_raw.splitlines():
        clean = branch.strip()
        if not clean or clean.endswith("/HEAD"):
            continue
        if clean.startswith("origin/"):
            clean = clean.removeprefix("origin/")
        if clean == main_branch:
            continue
        if clean not in candidates:
            candidates.append(clean)

    for branch in local_raw.splitlines():
        clean = branch.strip()
        if not clean or clean == main_branch:
            continue
        if clean not in candidates:
            candidates.append(clean)

    return candidates


def get_repo_status(repo_path: Path) -> RepoStatus:
    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], repo_path)
    commit_iso = _run_git(["log", "-1", "--format=%cI"], repo_path)

    try:
        commit_dt = datetime.fromisoformat(commit_iso.replace("Z", "+00:00"))
        commit_label = commit_dt.strftime("%Y-%m-%d %H:%M:%S %z")
    except ValueError:
        commit_label = commit_iso

    return RepoStatus(branch=branch, last_commit_date=commit_label)


def update_repo(repo_path: Path, remote_name: str, main_branch: str) -> RepoStatus:
    _run_git(["fetch", "--all", "--prune"], repo_path)
    candidates = _candidate_branches(repo_path, main_branch=main_branch)
    target_branch = candidates[0] if candidates else main_branch

    _run_git(["checkout", target_branch], repo_path)
    _run_git(["pull", "--ff-only", remote_name, target_branch], repo_path)

    return get_repo_status(repo_path)
