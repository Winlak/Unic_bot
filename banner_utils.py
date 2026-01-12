from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image

import config
from media_probe import VideoInfo

logger = logging.getLogger(__name__)

BANNER_EXTENSIONS = (
    ".mp4",
    ".mov",
    ".webm",
    ".m4v",
    ".png",
    ".webp",
    ".jpg",
    ".jpeg",
)
BANNER_CANDIDATE_NAMES = (
    "banner",
    "overlay",
    "ad",
    "promo",
    "advert",
)


@dataclass
class BannerSpec:
    path: Path
    is_video: bool
    position: str
    mode: str
    strip_height: int
    width_ratio: float
    margin_px: int
    chromakey_color: Optional[str]


@dataclass
class BannerDecision:
    spec: Optional[BannerSpec]
    reason: str


def find_banner_path() -> Optional[Path]:
    if config.BANNER_PATH:
        path = Path(config.BANNER_PATH).expanduser()
        if path.exists():
            return path
        return None
    search_dirs = [config.BASE_DIR]
    for directory in search_dirs:
        for base in BANNER_CANDIDATE_NAMES:
            for ext in BANNER_EXTENSIONS:
                candidate = directory / f"{base}{ext}"
                if candidate.exists():
                    return candidate
    return None


def _banner_is_video(path: Path) -> bool:
    return path.suffix.lower() in {".mp4", ".mov", ".webm", ".m4v"}


def _extract_frames(path: Path, output_dir: Path, frames: int) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        config.FFMPEG_BINARY,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(path),
        "-vf",
        f"fps={frames},scale=320:-1",
        str(output_dir / "frame_%03d.jpg"),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return sorted(output_dir.glob("frame_*.jpg"))


def _edge_density(image: np.ndarray) -> float:
    gray = image.mean(axis=2)
    gx = np.abs(np.diff(gray, axis=1))
    gy = np.abs(np.diff(gray, axis=0))
    grad = np.pad(gx, ((0, 0), (0, 1)), mode="edge") + np.pad(gy, ((0, 1), (0, 0)), mode="edge")
    threshold = max(8.0, np.percentile(grad, 85))
    return float((grad > threshold).mean())


def analyze_text_density(path: Path, samples: int = 8, band_ratio: float = 0.18) -> tuple[float, float]:
    temp_dir = config.TMP_DIR / f"density_{path.stem}"
    if temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)
    temp_dir.mkdir(parents=True, exist_ok=True)
    try:
        frames = _extract_frames(path, temp_dir, samples)
    except Exception as exc:
        logger.warning("Failed to extract frames for density analysis: %s", exc)
        return 0.0, 0.0

    top_scores = []
    bottom_scores = []
    for frame in frames:
        img = Image.open(frame).convert("RGB")
        img.thumbnail((320, 1000))
        arr = np.array(img)
        h = arr.shape[0]
        band = max(1, int(h * band_ratio))
        top = arr[:band, :, :]
        bottom = arr[h - band :, :, :]
        top_scores.append(_edge_density(top))
        bottom_scores.append(_edge_density(bottom))
    if not top_scores:
        return 0.0, 0.0
    return float(np.mean(top_scores)), float(np.mean(bottom_scores))


def _median_corner_color(path: Path) -> Optional[str]:
    try:
        if path.suffix.lower() in {".png", ".webp", ".jpg", ".jpeg"}:
            image = Image.open(path).convert("RGB")
            image.thumbnail((64, 64))
        else:
            cmd = [
                config.FFMPEG_BINARY,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(path),
                "-frames:v",
                "1",
                "-vf",
                "scale=64:64",
                str(config.TMP_DIR / f"banner_probe_{path.stem}.png"),
            ]
            subprocess.run(cmd, check=True, capture_output=True)
            image = Image.open(config.TMP_DIR / f"banner_probe_{path.stem}.png").convert("RGB")
    except Exception as exc:
        logger.warning("Failed to sample banner corners: %s", exc)
        return None

    arr = np.array(image)
    corners = np.array(
        [
            arr[0, 0],
            arr[0, -1],
            arr[-1, 0],
            arr[-1, -1],
        ]
    )
    median = np.median(corners, axis=0).astype(int)
    return f"0x{median[0]:02x}{median[1]:02x}{median[2]:02x}"


def choose_banner_placement(input_path: Path, info: VideoInfo) -> BannerDecision:
    if not config.BANNER_ENABLED:
        return BannerDecision(spec=None, reason="banner disabled")
    path = find_banner_path()
    if not path:
        reason = "banner not found"
        if config.FAIL_ON_MISSING_BANNER:
            raise FileNotFoundError("Banner enabled but not found")
        return BannerDecision(spec=None, reason=reason)

    position = config.BANNER_POSITION.lower()
    if position not in {"top", "bottom", "auto"}:
        position = "auto"

    mode = config.BANNER_STRIP_MODE.lower()
    if mode not in {"auto", "overlay", "strip"}:
        mode = "auto"

    chosen_position = position
    chosen_mode = mode

    if position == "auto" or mode == "auto":
        top_density, bottom_density = analyze_text_density(input_path)
        if top_density == 0.0 and bottom_density == 0.0:
            top_density = bottom_density = 0.0
        if position == "auto":
            chosen_position = "bottom" if top_density > bottom_density else "top"
        if mode == "auto":
            threshold = 0.055
            if top_density > threshold and bottom_density > threshold:
                chosen_mode = "strip"
            else:
                chosen_mode = "overlay"


    min_dim = max(1, min(info.width, info.height))
    strip_height = max(2, int(info.height * config.BANNER_STRIP_RATIO))
    margin_px = max(2, int(min_dim * config.BANNER_MARGIN_RATIO))
    max_margin = max(2, int(min_dim * 0.08))
    margin_px = min(margin_px, max_margin)
    if strip_height <= 2 * margin_px + 2:
        if info.height > 0:
            strip_height = min(info.height, max(strip_height, 2 * margin_px + 2))
        else:
            strip_height = max(strip_height, 2 * margin_px + 2)

    chromakey_color = config.CHROMAKEY_COLOR or _median_corner_color(path)
    spec = BannerSpec(
        path=path,
        is_video=_banner_is_video(path),
        position=chosen_position,
        mode=chosen_mode,
        strip_height=strip_height,
        width_ratio=config.BANNER_WIDTH_RATIO,
        margin_px=margin_px,
        chromakey_color=chromakey_color,
    )
    return BannerDecision(spec=spec, reason=f"banner {chosen_position}/{chosen_mode}")


def build_banner_filter(spec: BannerSpec, base_label: str = "base") -> tuple[str, str]:
    margin = spec.margin_px

    banner_filters = [
        "setpts=PTS-STARTPTS",
        "format=rgba",
    ]
    if config.CHROMAKEY_ENABLED and spec.chromakey_color:
        banner_filters.append(
            f"chromakey={spec.chromakey_color}:{config.CHROMAKEY_SIMILARITY}:{config.CHROMAKEY_BLEND}"
        )

    banner_chain = ",".join(banner_filters)

    max_w_expr = f"max(2\\,{spec.width_ratio:.3f}*ref_w-2*{margin})"


    if spec.mode == "strip":
        strip_h = spec.strip_height
        if spec.position == "top":
            y_target = f"({strip_h}-h)/2"
        else:
            y_target = f"H-{strip_h}+(" + f"({strip_h}-h)/2)"
        y_banner = f"max({margin}\\,min({y_target}\\,H-h-{margin}))"
        max_h_expr = f"max(2\\,{strip_h}-2*{margin})"

        filters = [
            f"[{base_label}]scale=iw:ih*(1-{config.BANNER_STRIP_RATIO:.3f})[scaled]",
        ]
        if spec.position == "top":
            filters.append(
                f"[scaled]pad=iw:ih+{strip_h}:0:{strip_h}:color=black[canvas]"
            )
        else:
            filters.append(
                f"[scaled]pad=iw:ih+{strip_h}:0:0:color=black[canvas]"
            )
        filters.append(f"[1:v]{banner_chain}[banner_raw]")
        filters.append(
            f"[banner_raw][canvas]scale2ref=w={max_w_expr}:h={max_h_expr}:force_original_aspect_ratio=decrease[banner][base2]"
        )
        x_expr = f"max({margin}\\,min((W-w)/2\\,W-w-{margin}))"
        filters.append(
            f"[base2][banner]overlay=x={x_expr}:y={y_banner}:format=auto[vout]"

        )
        return ";".join(filters), "vout"

    if spec.position == "top":
        y_expr = f"max({margin}\\,min({margin}\\,H-h-{margin}))"
    else:
        y_expr = f"max({margin}\\,min(H-h-{margin}\\,H-h-{margin}))"

    band_height_expr = f"max(2\\,{config.BANNER_STRIP_RATIO:.3f}*ref_h)"
    max_h_expr = f"max(2\\,{band_height_expr}-2*{margin})"
    x_expr = f"max({margin}\\,min((W-w)/2\\,W-w-{margin}))"

    filters = [
        f"[{base_label}]null[canvas]",
        f"[1:v]{banner_chain}[banner_raw]",

        f"[banner_raw][canvas]scale2ref=w={max_w_expr}:h={max_h_expr}:force_original_aspect_ratio=decrease[banner][base2]",
        f"[base2][banner]overlay=x={x_expr}:y={y_expr}:format=auto[vout]",

    ]
    return ";".join(filters), "vout"
