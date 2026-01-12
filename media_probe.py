from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import config

logger = logging.getLogger(__name__)


@dataclass
class VideoInfo:
    width: int
    height: int
    duration: float
    fps: float


_DURATION_RE = re.compile(r"Duration: (\d+):(\d+):(\d+\.\d+)")
_VIDEO_RE = re.compile(r"Video:.*?(\d+)x(\d+)")
_FPS_RE = re.compile(r"(\d+(?:\.\d+)?) fps")


def _parse_duration(text: str) -> float:
    match = _DURATION_RE.search(text)
    if not match:
        return 0.0
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _parse_resolution(text: str) -> tuple[int, int]:
    match = _VIDEO_RE.search(text)
    if not match:
        return 0, 0
    return int(match.group(1)), int(match.group(2))


def _parse_fps(text: str) -> float:
    match = _FPS_RE.search(text)
    if not match:
        return 0.0
    try:
        return float(match.group(1))
    except ValueError:
        return 0.0


def _run_probe(cmd: list[str]) -> Optional[str]:
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError:
        logger.warning("Probe binary not found: %s", cmd[0])
        return None
    except subprocess.CalledProcessError as exc:
        logger.warning("Probe failed: %s", exc.stderr.strip())
        return None
    return result.stdout


def probe_video_info(path: Path) -> VideoInfo:
    cmd = [
        config.FFPROBE_BINARY,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,avg_frame_rate,r_frame_rate:format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    output = _run_probe(cmd)
    if output:
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        width = int(lines[0]) if len(lines) > 0 else 0
        height = int(lines[1]) if len(lines) > 1 else 0
        duration = float(lines[-1]) if lines else 0.0
        fps = 0.0
        if len(lines) >= 4:
            fps_raw = lines[2]
            fps_parts = fps_raw.split("/")
            if len(fps_parts) == 2 and fps_parts[1] != "0":
                fps = float(fps_parts[0]) / float(fps_parts[1])
        return VideoInfo(width=width, height=height, duration=max(duration, 0.0), fps=fps)

    cmd = [config.FFMPEG_BINARY, "-hide_banner", "-i", str(path)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        logger.warning("FFmpeg binary not found while probing")
        return VideoInfo(width=0, height=0, duration=0.0, fps=0.0)
    stderr = result.stderr or ""
    width, height = _parse_resolution(stderr)
    duration = _parse_duration(stderr)
    fps = _parse_fps(stderr)
    return VideoInfo(width=width, height=height, duration=max(duration, 0.0), fps=fps)


def detect_audio_stream(path: Path) -> bool:
    cmd = [
        config.FFPROBE_BINARY,
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=codec_type",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    output = _run_probe(cmd)
    if output is not None:
        return bool(output.strip())

    cmd = [config.FFMPEG_BINARY, "-hide_banner", "-i", str(path)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        logger.warning("FFmpeg binary not found while detecting audio")
        return True
    stderr = result.stderr or ""
    return "Audio:" in stderr
