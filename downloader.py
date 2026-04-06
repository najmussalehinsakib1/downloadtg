"""
downloader.py — Media metadata extraction and downloading via yt-dlp.
"""

import os
import uuid
import logging
from typing import Any

import yt_dlp  # type: ignore

logger = logging.getLogger(__name__)

DOWNLOAD_DIR = os.path.join(os.path.dirname(__file__), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

MAX_VIDEO_FORMATS = 6


def _human_size(size_bytes: int | None) -> str:
    if not size_bytes:
        return "~unknown"
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"~{size_bytes:.0f} {unit}"
        size_bytes /= 1024
    return f"~{size_bytes:.1f} TB"


def extract_formats(url: str) -> list[dict[str, Any]]:
    """
    Extract available formats. Returns list of dicts with 'label' and 'callback'.
    callback format: "dl|<video_id>|<audio_id>|<url>"
    """
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
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

    # Best audio-only format for merging
    audio_formats = [
        f for f in raw_formats
        if f.get("acodec", "none") != "none" and f.get("vcodec", "none") == "none"
    ]
    best_audio_id: str | None = None
    if audio_formats:
        best_audio = max(audio_formats, key=lambda f: f.get("abr") or f.get("tbr") or 0)
        best_audio_id = best_audio.get("format_id")

    # Collect unique video qualities
    seen_heights: set[int] = set()
    video_options: list[dict[str, Any]] = []

    sorted_formats = sorted(raw_formats, key=lambda f: (f.get("height") or 0), reverse=True)

    for fmt in sorted_formats:
        height = fmt.get("height")
        vcodec = fmt.get("vcodec", "none")
        acodec = fmt.get("acodec", "none")
        fmt_id = fmt.get("format_id")
        ext = fmt.get("ext", "mp4")

        if not height or vcodec == "none" or not fmt_id:
            continue
        if height in seen_heights:
            continue
        seen_heights.add(height)

        size_bytes = fmt.get("filesize") or fmt.get("filesize_approx")

        # Determine audio part
        if acodec != "none":
            audio_part = "self"
        elif best_audio_id:
            audio_part = best_audio_id
        else:
            audio_part = "none"

        label = f"📹 {height}p  ({_human_size(size_bytes)})  .{ext}"
        callback = f"dl|{fmt_id}|{audio_part}|{url}"
        video_options.append({"label": label, "callback": callback})

        if len(video_options) >= MAX_VIDEO_FORMATS:
            break

    # Audio-only option
    if audio_formats:
        best_audio = max(audio_formats, key=lambda f: f.get("abr") or f.get("tbr") or 0)
        size_bytes = best_audio.get("filesize") or best_audio.get("filesize_approx")
        audio_id = best_audio.get("format_id", "bestaudio")
        video_options.append({
            "label": f"🎵 Audio Only  ({_human_size(size_bytes)})  .mp3",
            "callback": f"dl|AUDIO_ONLY|{audio_id}|{url}",
        })

    if not video_options:
        video_options.append({
            "label": "⬇️ Best Available Quality",
            "callback": f"dl|BEST|none|{url}",
        })

    return video_options


def download_media(url: str, video_id: str, audio_id: str) -> tuple[str, int]:
    """
    Download using explicit format IDs.
    video_id: format_id, "AUDIO_ONLY", or "BEST"
    audio_id: format_id, "self" (already has audio), or "none"
    """
    unique_id = uuid.uuid4().hex
    output_template = os.path.join(DOWNLOAD_DIR, f"{unique_id}.%(ext)s")

    ydl_opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "outtmpl": output_template,
        "merge_output_format": "mp4",
    }

    if video_id == "AUDIO_ONLY":
        ydl_opts["format"] = audio_id if audio_id not in ("none", "self") else "bestaudio/best"
        ydl_opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]
    elif video_id == "BEST":
        ydl_opts["format"] = "bestvideo+bestaudio/best"
    elif audio_id == "self":
        ydl_opts["format"] = video_id
    elif audio_id not in ("none", ""):
        ydl_opts["format"] = f"{video_id}+{audio_id}"
    else:
        ydl_opts["format"] = video_id

    logger.info("Downloading | url=%s | format=%s", url, ydl_opts["format"])

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            ydl.download([url])
        except yt_dlp.utils.DownloadError as exc:
            # Fallback to best available
            logger.warning("Format failed (%s), retrying with best...", exc)
            ydl_opts["format"] = "bestvideo+bestaudio/best"
            try:
                ydl.download([url])
            except yt_dlp.utils.DownloadError as exc2:
                raise FileNotFoundError(f"yt-dlp download failed: {exc2}") from exc2

    matched = [
        os.path.join(DOWNLOAD_DIR, f)
        for f in os.listdir(DOWNLOAD_DIR)
        if f.startswith(unique_id)
    ]

    if not matched:
        raise FileNotFoundError("Download succeeded but output file not found.")

    file_path = matched[0]
    file_size = os.path.getsize(file_path)
    logger.info("Done | path=%s | size=%d bytes", file_path, file_size)
    return file_path, file_size
