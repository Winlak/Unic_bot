from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path
from typing import Optional

import config


def get_file_size_bytes(path: Path) -> int:
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0


def probe_duration_seconds(path: Path) -> float:
    cmd = [
        config.FFPROBE_BINARY,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=nw=1:nk=1",
        str(path),
    ]
    try:
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return 0.0
    try:
        duration = float(result.stdout.strip())
    except ValueError:
        return 0.0
    return max(duration, 0.0)


def _run_ffmpeg(cmd: list[str]) -> None:
    process = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if process.returncode != 0:
        raise RuntimeError(process.stderr.decode().strip() or "FFmpeg failed")


def _cleanup_pass_logs(base: Path) -> None:
    for suffix in ("-0.log", "-0.log.mbtree", "-0.log.temp", "-0.log.mbtree.temp"):
        file_path = Path(f"{base}{suffix}")
        if file_path.exists():
            try:
                file_path.unlink()
            except OSError:
                pass


def _build_scale_filter(limit: Optional[int]) -> Optional[str]:
    if not limit:
        return None
    return f"scale=min({limit},iw):-2:flags=lanczos"


def transcode_to_size_limit(src: Path, dst: Path, target_bytes: int, max_iters: int = 4) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    duration = probe_duration_seconds(src)
    if duration <= 0:
        duration = max(1.0, get_file_size_bytes(src) / 4_000_000)
    base_total_bps = max(250_000, int(target_bytes * 8 / duration))
    passlog_base = config.TMP_DIR / f"passlog_{uuid.uuid4().hex}"
    scale_steps = [None, 720, 540, 480]
    audio_bitrates = [
        config.TELEGRAM_AUDIO_BITRATE,
        112_000,
        config.TELEGRAM_AUDIO_BITRATE_LOW,
        config.TELEGRAM_AUDIO_BITRATE_LOW,
    ]

    try:
        for idx in range(min(max_iters, len(scale_steps))):
            scale_limit = scale_steps[idx]
            audio_bps = audio_bitrates[idx]
            effective_target = max(200_000, int(base_total_bps * (0.9 ** idx)))
            video_bps = max(200_000, effective_target - audio_bps - 120_000)
            max_rate = int(video_bps * 1.2)
            buf_size = int(video_bps * 2)
            scale_filter = _build_scale_filter(scale_limit)
            common_args = [
                config.FFMPEG_BINARY,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(src),
            ]
            if scale_filter:
                vf_args = ["-vf", scale_filter]
            else:
                vf_args = []

            passlog_arg = ["-passlogfile", str(passlog_base)]
            preset_arg = ["-preset", config.TELEGRAM_TRANSCODE_PRESET]
            profile_args = [
                "-profile:v",
                "high",
                "-pix_fmt",
                "yuv420p",
            ]

            cmd_pass1 = (
                common_args
                + vf_args
                + [
                    "-c:v",
                    "libx264",
                    "-b:v",
                    str(video_bps),
                    "-maxrate",
                    str(max_rate),
                    "-bufsize",
                    str(buf_size),
                ]
                + preset_arg
                + profile_args
                + passlog_arg
                + [
                    "-pass",
                    "1",
                    "-an",
                    "-f",
                    "mp4",
                    os.devnull,
                ]
            )
            _run_ffmpeg(cmd_pass1)

            cmd_pass2 = (
                common_args
                + vf_args
                + [
                    "-c:v",
                    "libx264",
                    "-b:v",
                    str(video_bps),
                    "-maxrate",
                    str(max_rate),
                    "-bufsize",
                    str(buf_size),
                ]
                + preset_arg
                + profile_args
                + passlog_arg
                + [
                    "-pass",
                    "2",
                    "-c:a",
                    "aac",
                    "-b:a",
                    str(audio_bps),
                    "-movflags",
                    "+faststart",
                    str(dst),
                ]
            )
            _run_ffmpeg(cmd_pass2)

            if get_file_size_bytes(dst) <= target_bytes:
                return dst
        raise RuntimeError("Не удалось ужать видео до лимита Telegram")
    finally:
        _cleanup_pass_logs(passlog_base)
