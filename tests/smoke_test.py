from __future__ import annotations

import argparse
import subprocess
import sys
import uuid
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

import config
from banner_utils import choose_banner_placement
from ffmpeg_runner import build_ffmpeg_command
from media_probe import probe_video_info
from video_params import generate_variant_params


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True)


def create_test_video(path: Path, text: str, y_pos: str) -> None:
    cmd = [
        config.FFMPEG_BINARY,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=size=1080x1920:rate=30:duration=4",
        "-vf",
        (
            "drawtext=text='" + text + "':fontcolor=white:fontsize=64:"
            "box=1:boxcolor=black@0.6:boxborderw=16:"
            f"x=(w-text_w)/2:y={y_pos}"
        ),
        str(path),
    ]
    _run(cmd)


def create_banner(path: Path) -> None:
    cmd = [
        config.FFMPEG_BINARY,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=c=0x2ca0fc:size=800x200:duration=2",
        "-vf",
        "drawbox=x=20:y=20:w=760:h=160:color=white@1:t=fill",
        str(path),
    ]
    _run(cmd)



def _filter_complex_from_command(command: list[str]) -> str:
    if "-filter_complex" not in command:
        return ""
    index = command.index("-filter_complex")
    return command[index + 1]


def _assert_safe_fit(command: list[str]) -> None:
    filter_complex = _filter_complex_from_command(command)
    assert "force_original_aspect_ratio=decrease" in filter_complex
    assert "overlay=x=max(" in filter_complex
    assert "overlay=y=max(" in filter_complex
    assert "max(2" in filter_complex



def run_pipeline(input_path: Path, output_path: Path) -> str:
    info = probe_video_info(input_path)
    decision = choose_banner_placement(input_path, info)
    params = generate_variant_params(123)
    command = build_ffmpeg_command(input_path, output_path, params, decision)
    _assert_safe_fit(command)

    _run(command)
    return decision.spec.position if decision.spec else "none"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workdir", default=str(config.TMP_DIR))
    args = parser.parse_args()
    workdir = Path(args.workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    banner_path = workdir / "banner.mp4"
    create_banner(banner_path)
    config.BANNER_PATH = str(banner_path)

    bottom_text = workdir / f"bottom_{uuid.uuid4().hex}.mp4"
    top_text = workdir / f"top_{uuid.uuid4().hex}.mp4"
    create_test_video(bottom_text, "BOTTOM", "h-200")
    create_test_video(top_text, "TOP", "100")

    output_bottom = workdir / f"out_bottom_{uuid.uuid4().hex}.mp4"
    output_top = workdir / f"out_top_{uuid.uuid4().hex}.mp4"

    config.BANNER_STRIP_MODE = "overlay"
    pos_bottom = run_pipeline(bottom_text, output_bottom)
    pos_top = run_pipeline(top_text, output_top)

    config.BANNER_STRIP_MODE = "strip"
    output_strip = workdir / f"out_strip_{uuid.uuid4().hex}.mp4"
    run_pipeline(bottom_text, output_strip)

    assert output_bottom.exists() and output_bottom.stat().st_size > 0
    assert output_top.exists() and output_top.stat().st_size > 0
    assert output_strip.exists() and output_strip.stat().st_size > 0
    assert pos_bottom == "top", f"Expected banner on top for bottom text, got {pos_bottom}"
    assert pos_top == "bottom", f"Expected banner on bottom for top text, got {pos_top}"


if __name__ == "__main__":
    main()
