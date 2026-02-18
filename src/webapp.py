from __future__ import annotations

from pathlib import Path

from plantcamera.app import run


def run_web_server(
    host: str,
    port: int,
    repo_root: Path,
    remote_name: str,
    main_branch: str,
    update_endpoint: str,
    test_mode: bool = False,
) -> None:
    run(
        host=host,
        port=port,
        repo_root=repo_root,
        remote_name=remote_name,
        main_branch=main_branch,
        update_endpoint=update_endpoint,
        test_mode=test_mode,
    )
