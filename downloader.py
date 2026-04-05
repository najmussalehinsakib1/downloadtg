"""
downloader.py — Media metadata extraction and downloading via yt-dlp.

This module is intentionally free of Telegram-specific code so it can be
tested and reused independently.
"""

import os
import uuid
import logging
from typing import Any

import yt_dlp  # type: ignore

logger = logging.getLogger(__name__)

# Directory where downloaded files are temporarily stored
DOWNLOAD_DIR = os.path.join(os.path.dirname(__file__), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Maximum number of video-quality options shown to the user
MAX_VIDEO_FORMATS = 6


def _human_size(size_bytes: int | None) -> str:
    """Convert bytes to a human-readable string (e.g. '45 MB')."""
    if not size_bytes:
        return "unknown size"
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.0f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def extract_formats(url: str) -> list[dict[str, Any]]:
    """
    Use yt-dlp to fetch all available formats for *url*.

    Returns a list of dicts, each containing:
        - label    : display text shown on the inline button
        - callback : callback_data string ("dl|<format_id>|<url>")

    Raises ValueError for unsupported / private URLs.
    """
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,   # metadata only
        "noplaylist": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
        except yt_dlp.utils.DownloadError as exc:
            raise ValueError(str(exc)) from exc

    if info is None:
        raise ValueError("yt-dlp returned no information for this URL.")

    raw_formats: list[dict] = info.get("formats", [])

    # ── Collect unique video qualities ─────────────────────────────────────────
    seen_heights: set[int] = set()
    video_options: list[dict[str, Any]] = []

    # Sort by height descending so we offer best quality first
    sorted_formats = sorted(
        raw_formats,
        key=lambda f: (f.get("height") or 0),
        reverse=True,
    )

    for fmt in sorted_formats:
        height = fmt.get("height")
        vcodec = fmt.get("vcodec", "none")
        ext = fmt.get("ext", "mp4")

        # Skip audio-only streams for this section
        if not height or vcodec == "none":
            continue

        if height in seen_heights:
            continue
        seen_heights.add(height)

        # Prefer combined streams; fall back to video+audio merge
        size_bytes = fmt.get("filesize") or fmt.get("filesize_approx")
        size_label = _human_size(size_bytes)

        # Use a format selector that merges best audio into this resolution
        format_selector = f"bestvideo[height<={height}]+bestaudio/best[height<={height}]"

        label = f"📹 {height}p  ({size_label})  .{ext}"
        callback = f"dl|{format_selector}|{url}"

        video_options.append({"label": label, "callback": callback})

        if len(video_options) >= MAX_VIDEO_FORMATS:
            break

    # ── Audio-only option ──────────────────────────────────────────────────────
    audio_formats = [
        f for f in raw_formats
        if f.get("acodec") != "none" and f.get("vcodec") == "none"
    ]
    if audio_formats:
        # Pick the highest-bitrate audio stream for size estimate
        best_audio = max(
            audio_formats,
            key=lambda f: f.get("abr") or f.get("tbr") or 0,
        )
        size_bytes = best_audio.get("filesize") or best_audio.get("filesize_approx")
        label = f"🎵 Audio Only  ({_human_size(size_bytes)})  .mp3"
        video_options.append({"label": label, "callback": f"dl|bestaudio/best|{url}::audio"})

    if not video_options:
        # Last resort: offer generic "best" option
        video_options.append({
            "label": "⬇️ Best Available Quality",
            "callback": f"dl|best|{url}",
        })

    return video_options


def download_media(url: str, format_id: str) -> tuple[str, int]:
    """
    Download *url* using *format_id* (a yt-dlp format selector string).

    Returns:
        (file_path, file_size_in_bytes)

    Raises:
        FileNotFoundError if the downloaded file cannot be located.
    """
    # Detect audio-only flag embedded at the end of the URL
    audio_only = url.endswith("::audio")
    if audio_only:
        url = url[: -len("::audio")]

    # Unique output template to avoid filename collisions
    unique_id = uuid.uuid4().hex
    output_template = os.path.join(DOWNLOAD_DIR, f"{unique_id}.%(ext)s")

    ydl_opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "outtmpl": output_template,
        "merge_output_format": "mp4",  # ensure merged output is mp4
    }

    if audio_only:
        # Convert to MP3
        ydl_opts["format"] = "bestaudio/best"
        ydl_opts["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ]
    else:
        ydl_opts["format"] = format_id

    logger.info("Starting download | url=%s | format=%s", url, format_id)

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            ydl.download([url])
        except yt_dlp.utils.DownloadError as exc:
            raise FileNotFoundError(f"yt-dlp download failed: {exc}") from exc

    # ── Locate the output file ─────────────────────────────────────────────────
    # yt-dlp may change the extension, so we search by UUID prefix
    matched: list[str] = [
        os.path.join(DOWNLOAD_DIR, f)
        for f in os.listdir(DOWNLOAD_DIR)
        if f.startswith(unique_id)
    ]

    if not matched:
        raise FileNotFoundError(
            "Download appeared to succeed but the output file was not found."
        )

    file_path = matched[0]
    file_size = os.path.getsize(file_path)
    logger.info("Download complete | path=%s | size=%d bytes", file_path, file_size)

    return file_path, file_size
