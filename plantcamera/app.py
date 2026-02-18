from __future__ import annotations

from pathlib import Path

from plantcamera.config import AppConfig, load_config
from plantcamera.infra.camera_termux import capture_photo
from plantcamera.infra.ffmpeg import encode_timelapse, list_encoders
from plantcamera.services.timelapse import TimelapseService
from plantcamera.services.updater import UpdaterService
from plantcamera.web.server import WebApplication, run_server


def build_app(config: AppConfig, repo_root: Path, test_mode: bool = False) -> WebApplication:
    app_logger = print
    timelapse = TimelapseService(
        base_media_dir=config.media_base_dir,
        capture_photo=capture_photo,
        encode_timelapse=encode_timelapse,
        list_encoders=list_encoders,
        capture_interval_seconds=config.capture_interval_seconds,
        live_view_interval_seconds=config.live_view_interval_seconds,
        session_image_count=config.session_image_count,
        fps=config.timelapse_fps,
        codec=config.timelapse_codec,
        logger=lambda m: app_logger(f"[timelapse] {m}"),
    )
    updater = UpdaterService(
        repo_root=repo_root,
        remote_name=config.update_remote,
        main_branch=config.update_branch,
        logger=lambda m: app_logger(f"[updater] {m}"),
    )
    return WebApplication(config=config, timelapse=timelapse, updater=updater, test_mode=test_mode)


def run(
    host: str | None = None,
    port: int | None = None,
    repo_root: Path | None = None,
    remote_name: str | None = None,
    main_branch: str | None = None,
    update_endpoint: str | None = None,
    test_mode: bool = False,
) -> None:
    config = load_config([] if test_mode else None)
    if host:
        config = AppConfig(**{**config.__dict__, "host": host})
    if port:
        config = AppConfig(**{**config.__dict__, "port": port})
    if remote_name:
        config = AppConfig(**{**config.__dict__, "update_remote": remote_name})
    if main_branch:
        config = AppConfig(**{**config.__dict__, "update_branch": main_branch})
    if update_endpoint:
        config = AppConfig(**{**config.__dict__, "update_endpoint": update_endpoint})
    app = build_app(config=config, repo_root=repo_root or Path.cwd(), test_mode=test_mode)
    run_server(app)
