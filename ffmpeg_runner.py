from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import List

import config
from video_params import VariantParams


class FFmpegProcessError(RuntimeError):
    pass


def _input_has_audio(path: Path) -> bool:
    cmd = [
        config.FFPROBE_BINARY,
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=sample_rate",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    try:
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return True
    except subprocess.CalledProcessError:
        return False
    return bool(result.stdout.strip())


def build_ffmpeg_command(input_path: Path, output_path: Path, params: VariantParams) -> List[str]:
    zoom = params.zoom
    video_filters = [
        f"scale=iw*{zoom:.5f}:ih*{zoom:.5f}:flags=lanczos",
        f"crop=iw/{zoom:.5f}:ih/{zoom:.5f}",
        "scale=iw:ih:flags=lanczos",
        f"eq=brightness={params.brightness:.5f}:contrast=1.0:saturation={params.saturation_factor:.5f}",
        "setpts=PTS-STARTPTS",
        f"noise=alls={params.noise_level}:allf=t",
    ]
    video_filter_chain = ",".join(video_filters)

    has_audio = _input_has_audio(input_path)
    audio_args: List[str]
    if has_audio:
        base_sr = config.AUDIO_BASE_SAMPLE_RATE
        adjusted_sr = max(
            config.MIN_AUDIO_SAMPLE_RATE,
            int(round(base_sr * params.pitch_factor))
        )
        pitch_inv = 1.0 / params.pitch_factor
        audio_filters = (
            f"aresample={base_sr}:osf=s32,"
            f"asetrate={adjusted_sr},"
            f"aresample={base_sr},"
            f"atempo={pitch_inv:.7f}"
        )
        audio_args = [
            "-af",
            audio_filters,
            "-c:a",
            "aac",
            "-b:a",
            "192k",
        ]
    else:
        audio_args = ["-an"]

    command = [
        config.FFMPEG_BINARY,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(input_path),
        "-vf",
        video_filter_chain,
        "-c:v",
        config.VIDEO_CODEC,
        "-preset",
        config.VIDEO_PRESET_QUALITY,
        "-crf",
        str(config.VIDEO_CRF_QUALITY),
        "-profile:v",
        "high",
        "-pix_fmt",
        "yuv420p",
    ]
    command.extend(audio_args)
    command.append("-shortest")
    command.extend([
        "-movflags",
        "+faststart",
        "-map_metadata",
        "-1",
        str(output_path),
    ])
    return command


async def run_ffmpeg(command: List[str]) -> None:
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise FFmpegProcessError(stderr.decode().strip() or "FFmpeg exited with error")
