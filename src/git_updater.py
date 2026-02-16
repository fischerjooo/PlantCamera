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


def _candidate_branches(repo_path: Path, remote_name: str, main_branch: str) -> list[str]:
    remote_raw = _run_git(["branch", "-r", "--format=%(refname:short)"], repo_path)
    local_raw = _run_git(["branch", "--format=%(refname:short)"], repo_path)

    remote_candidates: list[str] = []
    local_candidates: list[str] = []

    for branch in remote_raw.splitlines():
        clean = branch.strip()
        if not clean or clean.endswith("/HEAD"):
            continue

        remote_prefix = f"{remote_name}/"
        if clean.startswith(remote_prefix):
            clean = clean.removeprefix(remote_prefix)
        elif "/" in clean:
            continue

        if clean == main_branch or clean in remote_candidates:
            continue
        remote_candidates.append(clean)

    for branch in local_raw.splitlines():
        clean = branch.strip()
        if not clean or clean == main_branch or clean in local_candidates:
            continue
        local_candidates.append(clean)

    # Prefer remote branches first so updates can be pulled, then local-only branches.
    return sorted(remote_candidates) + sorted([b for b in local_candidates if b not in remote_candidates])


def _remote_branch_exists(repo_path: Path, remote_name: str, branch_name: str) -> bool:
    refs = _run_git(["ls-remote", "--heads", remote_name, branch_name], repo_path)
    return bool(refs)


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
    current_branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], repo_path)
    candidates = _candidate_branches(repo_path, remote_name=remote_name, main_branch=main_branch)

    if current_branch != main_branch:
        target_branch = current_branch
    elif candidates:
        target_branch = candidates[0]
    else:
        target_branch = main_branch

    _run_git(["checkout", target_branch], repo_path)

    if _remote_branch_exists(repo_path, remote_name=remote_name, branch_name=target_branch):
        _run_git(["pull", "--ff-only", remote_name, target_branch], repo_path)
    elif target_branch == main_branch:
        _run_git(["pull", "--ff-only", remote_name, main_branch], repo_path)

    return get_repo_status(repo_path)
