"""
downloader.py — Media metadata extraction and downloading via yt-dlp.
"""

import os
import uuid
import logging
import tempfile
from typing import Any

import yt_dlp  # type: ignore

logger = logging.getLogger(__name__)

DOWNLOAD_DIR = os.path.join(os.path.dirname(__file__), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

MAX_VIDEO_FORMATS = 6


def _get_cookies_file() -> str | None:
    """
    Railway environment variable COOKIES_CONTENT থেকে
    একটা temporary cookies.txt file বানিয়ে দেয়।
    যদি variable না থাকে তাহলে None return করে।
    """
    cookies_content = os.getenv("COOKIES_CONTENT", "").strip()
    if not cookies_content:
        return None
    try:
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        )
        tmp.write(cookies_content)
        tmp.close()
        logger.info("Cookies file created at: %s", tmp.name)
        return tmp.name
    except Exception as exc:
        logger.warning("Could not write cookies file: %s", exc)
        return None


def _human_size(size_bytes: int | None) -> str:
    if not size_bytes:
        return "unknown size"
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.0f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def _base_ydl_opts() -> dict[str, Any]:
    """
    সব yt-dlp call এ common options।
    Cookies থাকলে automatically add হয়।
    """
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        },
    }
    cookie_file = _get_cookies_file()
    if cookie_file:
        opts["cookiefile"] = cookie_file
    return opts


def extract_formats(url: str) -> list[dict[str, Any]]:
    """
    yt-dlp দিয়ে URL এর available formats বের করে।
    Returns list of dicts: label, format_id, audio_only
    """
    ydl_opts = _base_ydl_opts()
    ydl_opts["skip_download"] = True

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
        except yt_dlp.utils.DownloadError as exc:
            raise ValueError(str(exc)) from exc

    if info is None:
        raise ValueError("yt-dlp returned no information for this URL.")

    raw_formats: list[dict] = info.get("formats", [])

    seen_heights: set[int] = set()
    video_options: list[dict[str, Any]] = []

    sorted_formats = sorted(
        raw_formats,
        key=lambda f: (f.get("height") or 0),
        reverse=True,
    )

    for fmt in sorted_formats:
        height = fmt.get("height")
        vcodec = fmt.get("vcodec", "none")
        ext = fmt.get("ext", "mp4")

        if not height or vcodec == "none":
            continue
        if height in seen_heights:
            continue
        seen_heights.add(height)

        size_bytes = fmt.get("filesize") or fmt.get("filesize_approx")
        format_selector = f"bestvideo[height<={height}]+bestaudio/best[height<={height}]"

        video_options.append({
            "label": f"📹 {height}p  ({_human_size(size_bytes)})  .{ext}",
            "format_id": format_selector,
            "audio_only": False,
        })

        if len(video_options) >= MAX_VIDEO_FORMATS:
            break

    # Audio-only option
    audio_formats = [
        f for f in raw_formats
        if f.get("acodec") != "none" and f.get("vcodec") == "none"
    ]
    if audio_formats:
        best_audio = max(audio_formats, key=lambda f: f.get("abr") or f.get("tbr") or 0)
        size_bytes = best_audio.get("filesize") or best_audio.get("filesize_approx")
        video_options.append({
            "label": f"🎵 Audio Only  ({_human_size(size_bytes)})  .mp3",
            "format_id": "bestaudio/best",
            "audio_only": True,
        })

    if not video_options:
        video_options.append({
            "label": "⬇️ Best Available Quality",
            "format_id": "best",
            "audio_only": False,
        })

    return video_options


def download_media(url: str, format_id: str, audio_only: bool = False) -> tuple[str, int]:
    """
    yt-dlp দিয়ে media download করে।
    Returns: (file_path, file_size_in_bytes)
    """
    unique_id = uuid.uuid4().hex
    output_template = os.path.join(DOWNLOAD_DIR, f"{unique_id}.%(ext)s")

    ydl_opts = _base_ydl_opts()
    ydl_opts.update({
        "outtmpl": output_template,
        "merge_output_format": "mp4",
    })

    if audio_only:
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

    logger.info("Downloading | url=%s | format=%s | audio_only=%s", url, format_id, audio_only)

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            ydl.download([url])
        except yt_dlp.utils.DownloadError as exc:
            raise FileNotFoundError(f"yt-dlp download failed: {exc}") from exc

    matched: list[str] = [
        os.path.join(DOWNLOAD_DIR, f)
        for f in os.listdir(DOWNLOAD_DIR)
        if f.startswith(unique_id)
    ]

    if not matched:
        raise FileNotFoundError("Download file not found after completion.")

    file_path = matched[0]
    file_size = os.path.getsize(file_path)
    logger.info("Done | path=%s | size=%d bytes", file_path, file_size)

    return file_path, file_size
