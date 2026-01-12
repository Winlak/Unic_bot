from __future__ import annotations

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent


def _load_dotenv() -> None:
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_dotenv()


def _env_bool(key: str, default: bool) -> bool:
    value = os.getenv(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(key: str, default: int) -> int:
    value = os.getenv(key)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    value = os.getenv(key)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


BOT_TOKEN_DEFAULT = ""
OWNER_TELEGRAM_ID_DEFAULT = 0

BOT_TOKEN = os.getenv("BOT_TOKEN", os.getenv("UNIC_BOT_TOKEN", BOT_TOKEN_DEFAULT))
OWNER_TELEGRAM_ID = _env_int(
    "OWNER_TELEGRAM_ID",
    _env_int("UNIC_OWNER_TELEGRAM_ID", OWNER_TELEGRAM_ID_DEFAULT),
)

ALLOWED_VARIANT_RANGE = (1, 5)
TELEGRAM_RETRY_ATTEMPTS = 3
TELEGRAM_DOWNLOAD_TIMEOUT = 300

FFMPEG_BINARY = os.getenv("UNIC_FFMPEG_BINARY", "ffmpeg")
FFPROBE_BINARY = os.getenv("UNIC_FFPROBE_BINARY", "ffprobe")

MIN_AUDIO_SAMPLE_RATE = 8000
AUDIO_BASE_SAMPLE_RATE = 48000
TELEGRAM_MAX_UPLOAD_MB = 49
TELEGRAM_AUDIO_BITRATE = 128_000
TELEGRAM_AUDIO_BITRATE_LOW = 96_000
TMP_DIR = BASE_DIR / "tmp"
TMP_DIR.mkdir(exist_ok=True)

ZOOM_RANGE = (1.02, 1.05)
BRIGHTNESS_RANGE = (-0.015, 0.015)
SATURATION_DELTA_RANGE = (-0.02, 0.02)
NOISE_RANGE = (0.003, 0.012)
AUDIO_PITCH_SHIFT_RANGE = (-0.015, 0.015)
FILE_CLEANUP_TTL_MINUTES = 60

VIDEO_CODEC = "libx264"
VIDEO_CRF_QUALITY = 18
VIDEO_CRF_FAST = 20
VIDEO_PRESET_QUALITY = "slow"
VIDEO_PRESET_FAST = "medium"
TELEGRAM_TRANSCODE_PRESET = "slow"
ALLOWED_VIDEO_MIME_PREFIX = "video"

BANNER_ENABLED = _env_bool("UNIC_BANNER_ENABLED", True)
BANNER_PATH = os.getenv("UNIC_BANNER_PATH", "")
BANNER_POSITION = os.getenv("UNIC_BANNER_POSITION", "auto")
BANNER_STRIP_MODE = os.getenv("UNIC_BANNER_STRIP_MODE", "auto")
BANNER_STRIP_RATIO = _env_float("UNIC_BANNER_STRIP_RATIO", 0.20)
BANNER_WIDTH_RATIO = _env_float("UNIC_BANNER_WIDTH_RATIO", 0.86)
BANNER_MARGIN_RATIO = _env_float("UNIC_BANNER_MARGIN_RATIO", 0.03)
CHROMAKEY_ENABLED = _env_bool("UNIC_CHROMAKEY_ENABLED", True)
CHROMAKEY_SIMILARITY = _env_float("UNIC_CHROMAKEY_SIMILARITY", 0.18)
CHROMAKEY_BLEND = _env_float("UNIC_CHROMAKEY_BLEND", 0.02)
CHROMAKEY_COLOR = os.getenv("UNIC_CHROMAKEY_COLOR", "") or None
FAIL_ON_MISSING_BANNER = _env_bool("UNIC_FAIL_ON_MISSING_BANNER", False)
