from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

import yt_dlp

YOUTUBE_URL_RE = re.compile(r"(https?://)?(www\.)?(youtube\.com|youtu\.be)/[^\s]+", re.IGNORECASE)


class YouTubeDownloadError(RuntimeError):
    pass


@dataclass
class YouTubeDownloadResult:
    file_path: Path
    title: str


def extract_youtube_url(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    match = YOUTUBE_URL_RE.search(text)
    if not match:
        return None
    url = match.group(0).rstrip("),.")
    if not url.startswith("http"):
        url = "https://" + url
    return url


def _download_sync(url: str, destination: Path) -> Tuple[Path, str]:
    destination.mkdir(parents=True, exist_ok=True)
    outtmpl = destination / "yt_%(id)s.%(ext)s"
    ydl_opts = {
        "format": "b[ext=mp4][height<=1080]+ba/best[ext=mp4]/best",
        "outtmpl": str(outtmpl),
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": True,
        "merge_output_format": "mp4",
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = Path(ydl.prepare_filename(info)).with_suffix(".mp4")
    except Exception as exc:  # noqa: BLE001
        raise YouTubeDownloadError(str(exc)) from exc
    if not file_path.exists():
        raise YouTubeDownloadError("Файл не был скачан")
    title = info.get("title") if isinstance(info, dict) else "video"
    return file_path, f"{title or 'video'}.mp4"


async def download_youtube_video(url: str, destination: Path) -> YouTubeDownloadResult:
    file_path, title = await asyncio.to_thread(_download_sync, url, destination)
    return YouTubeDownloadResult(file_path=file_path, title=title)

