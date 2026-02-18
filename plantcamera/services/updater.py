from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from plantcamera.infra.git_cli import run_git
from plantcamera.infra.process import restart_process


@dataclass(frozen=True)
class RepoStatus:
    branch: str
    last_commit_date: str


def select_update_branch(current_branch: str, main_branch: str, candidates: list[str], has_remote: bool) -> str:
    if current_branch not in {main_branch, "HEAD"} and has_remote:
        return current_branch
    if current_branch not in {main_branch, "HEAD"} and not has_remote:
        return main_branch
    if candidates:
        return candidates[0]
    return main_branch


class UpdaterService:
    def __init__(self, repo_root: Path, remote_name: str, main_branch: str, logger: Callable[[str], None]) -> None:
        self.repo_root = repo_root
        self.remote_name = remote_name
        self.main_branch = main_branch
        self.logger = logger

    def _candidate_branches(self) -> list[str]:
        remote_raw = run_git(self.repo_root, ["branch", "-r", "--format=%(refname:short)"])
        names: list[str] = []
        prefix = f"{self.remote_name}/"
        for branch in remote_raw.splitlines():
            clean = branch.strip()
            if not clean or clean.endswith("/HEAD"):
                continue
            if clean.startswith(prefix):
                clean = clean.removeprefix(prefix)
            if clean not in {self.main_branch} and clean not in names:
                names.append(clean)
        return sorted(names)

    def _remote_branch_exists(self, branch_name: str) -> bool:
        refs = run_git(self.repo_root, ["ls-remote", "--heads", self.remote_name, branch_name])
        return bool(refs)

    def get_status(self) -> RepoStatus:
        branch = run_git(self.repo_root, ["rev-parse", "--abbrev-ref", "HEAD"])
        commit_iso = run_git(self.repo_root, ["log", "-1", "--format=%cI"])
        try:
            commit_date = datetime.fromisoformat(commit_iso.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M:%S %z")
        except ValueError:
            commit_date = commit_iso
        return RepoStatus(branch=branch, last_commit_date=commit_date)

    def update_repo(self) -> RepoStatus:
        run_git(self.repo_root, ["fetch", "--all", "--prune"])
        current = run_git(self.repo_root, ["rev-parse", "--abbrev-ref", "HEAD"])
        target = select_update_branch(current, self.main_branch, self._candidate_branches(), self._remote_branch_exists(current))
        run_git(self.repo_root, ["checkout", target])
        if self._remote_branch_exists(target):
            run_git(self.repo_root, ["pull", "--ff-only", self.remote_name, target])
        self.logger(f"Update completed on branch {target}")
        return self.get_status()

    def schedule_restart(self) -> None:
        self.logger("Restarting process")
        restart_process()
