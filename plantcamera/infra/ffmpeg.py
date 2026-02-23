from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path


def list_encoders() -> set[str]:
    process = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], check=True, capture_output=True, text=True)
    encoders: set[str] = set()
    for line in process.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].startswith("V"):
            encoders.add(parts[1])
    return encoders


def rotate_image_left(image_path: Path) -> None:
    temporary_output = image_path.with_suffix(".rotated.jpg")
    temporary_output.unlink(missing_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-y",
            "-i",
            str(image_path),
            "-vf",
            "transpose=2",
            str(temporary_output),
        ],
        check=True,
        capture_output=True,
    )
    temporary_output.replace(image_path)


def estimate_black_ratio(image_path: Path) -> float | None:
    filtergraph = f"movie={image_path},blackframe=amount=90:threshold=32"
    try:
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                filtergraph,
                "-show_entries",
                "frame_tags=lavfi.blackframe.pblack",
                "-of",
                "default=nw=1:nk=1",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return None
    values = [line.strip() for line in probe.stdout.splitlines() if line.strip()]
    if not values:
        return 0.0
    try:
        return float(values[-1]) / 100.0
    except ValueError:
        return None


def normalize_image_full_hd(image_path: Path, quality: int = 6) -> None:
    """
    Convert image to exactly 1920x1080 (Full HD) and recompress it to reduce size.
    Preserves source aspect ratio by scaling to fit and padding with black bars.
    """
    temporary_output = image_path.with_suffix(".fhd.jpg")
    temporary_output.unlink(missing_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-y",
            "-i",
            str(image_path),
            "-vf",
            "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black",
            "-q:v",
            str(quality),
            str(temporary_output),
        ],
        check=True,
        capture_output=True,
    )
    temporary_output.replace(image_path)


def _probe_first_image_resolution(image_glob: Path) -> tuple[int, int] | None:
    """
    Uses ffprobe to get the resolution of the first image matched by the glob.
    Returns (width, height) or None if no images / probe fails.
    """
    # Path is expected like: /sdcard/.../frame_*.jpg
    # We need to resolve the first matching file in the parent directory.
    parent = image_glob.parent
    pattern = image_glob.name
    try:
        first = next(parent.glob(pattern))
    except StopIteration:
        return None

    # ffprobe can read single images and report width/height.
    try:
        p = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "csv=p=0:s=x",
                str(first),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        out = p.stdout.strip()
        if "x" not in out:
            return None
        w_s, h_s = out.split("x", 1)
        return int(w_s), int(h_s)
    except Exception:
        return None


def _needs_downscale_for_h264(width: int, height: int) -> bool:
    """
    libx264 operates in 16x16 macroblocks. Many H.264 level constraints bite on very large frames.
    If macroblocks/frame is extremely high, proactively downscale.
    """
    mb_w = (width + 15) // 16
    mb_h = (height + 15) // 16
    mb_per_frame = mb_w * mb_h
    # The failure you hit was at 155,952 MB/frame. Use a conservative threshold well below that.
    return mb_per_frame > 120_000


def _build_scale_filter(width: int, height: int, max_long_edge: int) -> str:
    """
    Scale so that the long edge is <= max_long_edge, preserve aspect ratio,
    and keep dimensions divisible by 2 (required for yuv420p).
    """
    if width >= height:
        # width is long edge
        return f"scale={max_long_edge}:-2"
    return f"scale=-2:{max_long_edge}"


def encode_timelapse(
    image_glob: Path,
    output_file: Path,
    fps: int,
    codec: str,
    *,
    max_long_edge: int | None = 2160,
    crf: int | None = None,
    preset: str | None = "veryfast",
) -> None:
    """
    Encodes a timelapse from images.

    Fixes the 'frame MB size ... > level limit' issue (common with huge photos on H.264)
    by automatically downscaling when using libx264 / h264-like encoders.

    Args:
        image_glob: Path with wildcard (e.g. Path("/sdcard/.../frame_*.jpg"))
        output_file: Target MP4 path.
        fps: Output framerate.
        codec: ffmpeg video encoder name (e.g. "libx264", "h264_mediacodec", "libx265").
        max_long_edge: If set, will downscale to this max long edge when needed.
                      Default 2160 (4K long edge) is a good timelapse target.
        crf: Optional constant quality factor for libx264/libx265 (e.g. 18-28). If None, ffmpeg defaults.
        preset: Optional x264/x265 preset (e.g. ultrafast, veryfast, medium, slow).
    """
    output_file.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output_file.with_suffix(".tmp.mp4")
    temporary_output.unlink(missing_ok=True)

    # Decide whether to apply scaling to avoid H.264 level/macroblock limits.
    vf_filters: list[str] = []
    res = _probe_first_image_resolution(image_glob)
    if res is not None:
        w, h = res
        is_h264_family = codec in {"libx264", "h264", "h264_mediacodec"} or "264" in codec
        if is_h264_family and max_long_edge is not None and _needs_downscale_for_h264(w, h):
            vf_filters.append(_build_scale_filter(w, h, max_long_edge))

    # Always force a widely compatible pixel format.
    vf_filters.append("format=yuv420p")
    vf = ",".join(vf_filters)

    cmd: list[str] = [
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-framerate",
        str(fps),
        "-pattern_type",
        "glob",
        "-i",
        str(image_glob),
        "-vf",
        vf,
        "-c:v",
        codec,
    ]

    # Quality settings where applicable.
    if preset:
        cmd += ["-preset", preset]
    if crf is not None:
        cmd += ["-crf", str(crf)]

    # Write output
    cmd.append(str(temporary_output))

    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or b"").decode(errors="replace")
        stdout = (e.stdout or b"").decode(errors="replace")

        # If we didn't scale on first attempt and we detect the macroblock/level error, retry with scaling.
        # (Useful when ffprobe couldn't read the image or the codec isn't detected by our heuristic.)
        level_limit_hit = bool(
            re.search(r"frame MB size .* > level limit", stderr, re.IGNORECASE)
            or re.search(r"level limit", stderr, re.IGNORECASE)
        )

        if level_limit_hit and max_long_edge is not None and "scale=" not in vf:
            retry_vf = ",".join([f"scale={max_long_edge}:-2", "format=yuv420p"])
            retry_cmd = cmd.copy()
            # replace vf argument
            vf_idx = retry_cmd.index("-vf")
            retry_cmd[vf_idx + 1] = retry_vf

            temporary_output.unlink(missing_ok=True)
            try:
                subprocess.run(retry_cmd, check=True, capture_output=True)
            except subprocess.CalledProcessError as e2:
                stderr2 = (e2.stderr or b"").decode(errors="replace")
                stdout2 = (e2.stdout or b"").decode(errors="replace")
                temporary_output.unlink(missing_ok=True)
                raise RuntimeError(
                    "ffmpeg failed (including retry with downscale).\n\n"
                    f"Command: {' '.join(retry_cmd)}\n\n"
                    f"STDERR:\n{stderr2}\n\nSTDOUT:\n{stdout2}"
                ) from e2
        else:
            temporary_output.unlink(missing_ok=True)
            raise RuntimeError(
                "ffmpeg failed.\n\n"
                f"Command: {' '.join(cmd)}\n\n"
                f"STDERR:\n{stderr}\n\nSTDOUT:\n{stdout}"
            ) from e

    size = temporary_output.stat().st_size if temporary_output.exists() else 0
    # Tiny MP4 files usually indicate a failed or empty conversion even if ffmpeg returned 0.
    if size < 256:
        temporary_output.unlink(missing_ok=True)
        raise RuntimeError(
            f"Generated video file is too small ({size} bytes). "
            "Conversion likely failed; check ffmpeg output and captured frames."
        )

    temporary_output.replace(output_file)


def merge_videos(video_files: list[Path], output_file: Path) -> None:
    if not video_files:
        raise RuntimeError("No videos provided for merge.")

    output_file.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output_file.with_suffix(".tmp.mp4")
    temporary_output.unlink(missing_ok=True)

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", delete=False) as concat_file:
        concat_path = Path(concat_file.name)
        for video in video_files:
            concat_file.write(f"file '{video.as_posix()}'\n")

    try:
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_path),
                "-c",
                "copy",
                str(temporary_output),
            ],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as error:
        temporary_output.unlink(missing_ok=True)
        message = (error.stderr or b"").decode("utf-8", errors="replace").strip() or str(error)
        raise RuntimeError(f"Video merge failed: {message}") from error
    finally:
        concat_path.unlink(missing_ok=True)

    if not temporary_output.exists() or temporary_output.stat().st_size < 256:
        temporary_output.unlink(missing_ok=True)
        raise RuntimeError("Merged video file is missing or too small.")

    temporary_output.replace(output_file)
