from __future__ import annotations

import argparse
import asyncio
import logging
import uuid
from pathlib import Path

import config
from banner_utils import choose_banner_placement
from ffmpeg_runner import FFmpegProcessError, build_ffmpeg_command, run_ffmpeg
from media_probe import probe_video_info
from video_params import generate_variant_params


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Unic video pipeline locally")
    parser.add_argument("--input", required=True, help="Path to input video")
    parser.add_argument("--outdir", required=True, help="Output directory")
    parser.add_argument("--variants", type=int, default=1, help="Number of variants")
    parser.add_argument("--seed", type=int, default=None, help="Random seed override")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    input_path = Path(args.input).expanduser().resolve()
    outdir = Path(args.outdir).expanduser().resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    info = probe_video_info(input_path)
    banner_decision = choose_banner_placement(input_path, info)
    if banner_decision.spec:
        logger.info("Banner decision: %s", banner_decision.reason)
    else:
        logger.warning("Banner skipped: %s", banner_decision.reason)

    for index in range(1, args.variants + 1):
        seed = args.seed if args.seed is not None else uuid.uuid4().int % 10_000_000
        params = generate_variant_params(seed)
        output_path = outdir / f"variant_{index}_{seed}.mp4"
        command = build_ffmpeg_command(input_path, output_path, params, banner_decision)
        try:
            await run_ffmpeg(command)
        except FFmpegProcessError as exc:
            logger.error("FFmpeg failed for variant %s: %s", index, exc)
            raise
        logger.info("Generated %s", output_path)
        logger.info("%s", params.as_report())


if __name__ == "__main__":
    asyncio.run(main())
