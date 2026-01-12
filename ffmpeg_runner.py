from __future__ import annotations

import asyncio
import logging
import subprocess
from pathlib import Path
from typing import List, Optional

import config
from banner_utils import BannerDecision, build_banner_filter, choose_banner_placement
from media_probe import detect_audio_stream, probe_video_info
from video_params import VariantParams


class FFmpegProcessError(RuntimeError):
    pass


logger = logging.getLogger(__name__)


def build_ffmpeg_command(
    input_path: Path,
    output_path: Path,
    params: VariantParams,
    banner_decision: Optional[BannerDecision] = None,
) -> List[str]:
    zoom = params.zoom
    video_filters = [
        f"scale=iw*{zoom:.5f}:ih*{zoom:.5f}:flags=lanczos",
        f"crop=iw/{zoom:.5f}:ih/{zoom:.5f}",
        "scale=iw:ih:flags=lanczos",
        f"eq=brightness={params.brightness:.5f}:contrast=1.0:saturation={params.saturation_factor:.5f}",
        "setpts=PTS-STARTPTS",
        f"noise=alls={params.noise_level}:allf=t",
    ]
    base_chain = ",".join(video_filters)

    has_audio = detect_audio_stream(input_path)
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

    info = probe_video_info(input_path)
    banner_decision = banner_decision or choose_banner_placement(input_path, info)

    input_args = [
        config.FFMPEG_BINARY,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(input_path),
    ]

    filter_complex = None
    map_args: List[str] = ["-map", "[vout]"]

    if banner_decision.spec:
        if banner_decision.spec.is_video:
            input_args.extend(["-stream_loop", "-1", "-i", str(banner_decision.spec.path)])
        else:
            input_args.extend(["-loop", "1", "-i", str(banner_decision.spec.path)])
        banner_filter, output_label = build_banner_filter(banner_decision.spec)
        filter_complex = ";".join([
            f"[0:v]{base_chain}[base]",
            banner_filter,
        ])
        map_args = ["-map", f"[{output_label}]"]
    else:
        filter_complex = f"[0:v]{base_chain}[vout]"

    command = input_args
    if filter_complex:
        command.extend(["-filter_complex", filter_complex])
    command.extend(map_args)
    command.extend([
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
    ])

    command.extend(audio_args)
    if has_audio:
        command.extend(["-map", "0:a?"])
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
        logger.error("FFmpeg failed: %s", " ".join(command))
        raise FFmpegProcessError(stderr.decode().strip() or "FFmpeg exited with error")
