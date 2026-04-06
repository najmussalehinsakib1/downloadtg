"""
bot.py — Telegram Downloader Bot
Main entry point: registers handlers and starts polling.
"""

import logging
import os
import asyncio
from dotenv import load_dotenv

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from downloader import extract_formats, download_media

# ── Logging setup ──────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Load environment ────────────────────────────────────────────────────────────
load_dotenv()
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN:
    raise EnvironmentError("BOT_TOKEN is not set in the environment variables.")

# FIX #4: Telegram Bot API actual upload limit is 50 MB, not 2 GB
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB


# ── /start command ──────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 *Welcome to Video Downloader Bot!*\n\n"
        "📎 Just send me a video link from:\n"
        "  • YouTube  🎬\n"
        "  • Facebook 📘\n"
        "  • Instagram 📷\n"
        "  • TikTok, Twitter, and 1000+ sites\n\n"
        "I'll show available qualities — pick one and I'll send the file! 🚀\n\n"
        "⚠️ Files larger than *50 MB* cannot be sent via Telegram Bot API.",
        parse_mode="Markdown",
    )


# ── /help command ───────────────────────────────────────────────────────────────
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "ℹ️ *How to use:*\n\n"
        "1. Paste any supported video URL\n"
        "2. Choose your preferred quality\n"
        "3. Wait while I download & send the file\n\n"
        "⚠️ Files larger than *50 MB* cannot be sent via Telegram Bot API.",
        parse_mode="Markdown",
    )


# ── URL handler ─────────────────────────────────────────────────────────────────
async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    url = update.message.text.strip()
    status_msg = await update.message.reply_text("🔍 Analysing link, please wait…")

    try:
        # FIX #3: Use asyncio.get_running_loop() instead of deprecated get_event_loop()
        loop = asyncio.get_running_loop()
        formats = await loop.run_in_executor(None, extract_formats, url)
    except ValueError as exc:
        # Escape special Markdown chars to avoid Telegram parse error
        safe_msg = str(exc).replace("_", r"\_").replace("*", r"\*").replace("`", r"\`").replace("[", r"\[")
        await status_msg.edit_text(f"❌ *Error:* {safe_msg}", parse_mode="Markdown")
        return
    except Exception as exc:
        logger.exception("Unexpected error during format extraction")
        await status_msg.edit_text(
            "❌ Could not extract video information. "
            "Make sure the URL is valid and publicly accessible.",
        )
        return

    if not formats:
        await status_msg.edit_text("⚠️ No downloadable formats found for this URL.")
        return

    # FIX #1: Store formats in user_data, use short index in callback_data
    # Telegram callback_data limit = 64 bytes. Old code put full URL+format in callback = CRASH.
    context.user_data["fmt_list"] = formats
    context.user_data["pending_url"] = url

    keyboard: list[list[InlineKeyboardButton]] = []
    for idx, fmt in enumerate(formats):
        label = fmt["label"]
        callback = f"dl|{idx}"  # always well under 64 bytes
        keyboard.append([InlineKeyboardButton(label, callback_data=callback)])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await status_msg.edit_text(
        "🎬 *Select quality / format:*",
        reply_markup=reply_markup,
        parse_mode="Markdown",
    )


# ── Callback query handler ──────────────────────────────────────────────────────
async def handle_quality_selection(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()

    # FIX #1: Parse index from "dl|<index>"
    try:
        _, idx_str = query.data.split("|", 1)
        idx = int(idx_str)
    except (ValueError, IndexError):
        await query.edit_message_text("❌ Invalid selection. Please try again.")
        return

    fmt_list: list | None = context.user_data.get("fmt_list")
    url: str | None = context.user_data.get("pending_url")

    if not fmt_list or url is None or idx >= len(fmt_list):
        await query.edit_message_text(
            "❌ Session expired. Please send the URL again."
        )
        return

    selected = fmt_list[idx]
    format_id: str = selected["format_id"]
    audio_only: bool = selected.get("audio_only", False)

    await query.edit_message_text("⬇️ Downloading… this may take a moment.")

    try:
        # FIX #3: Use asyncio.get_running_loop()
        loop = asyncio.get_running_loop()
        file_path, file_size = await loop.run_in_executor(
            None, download_media, url, format_id, audio_only
        )
    except FileNotFoundError as exc:
        await query.edit_message_text(f"❌ Download failed: {exc}")
        return
    except Exception as exc:
        logger.exception("Download error")
        await query.edit_message_text(f"❌ Unexpected error during download: {exc}")
        return

    # FIX #4: Check against real 50 MB Bot API limit
    if file_size > MAX_FILE_SIZE_BYTES:
        os.remove(file_path)
        await query.edit_message_text(
            "❌ *File too large!*\n"
            f"The file is `{file_size / (1024**2):.1f} MB`, "
            "but Telegram Bot API only allows up to *50 MB*.",
            parse_mode="Markdown",
        )
        return

    await query.edit_message_text("📤 Uploading to Telegram…")

    try:
        # FIX #2: audio_only flag now comes from stored fmt_list, not URL suffix hack
        if audio_only or file_path.endswith(".mp3"):
            with open(file_path, "rb") as audio_file:
                await query.message.reply_audio(
                    audio=audio_file,
                    caption="🎵 Here's your audio!",
                )
        else:
            with open(file_path, "rb") as video_file:
                await query.message.reply_video(
                    video=video_file,
                    caption="🎬 Here's your video!",
                    supports_streaming=True,
                )
        await query.edit_message_text("✅ Done! Enjoy your file.")
    except Exception as exc:
        logger.exception("Upload error")
        await query.edit_message_text(f"❌ Failed to upload file: {exc}")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info("Cleaned up: %s", file_path)


# ── Unknown message handler ─────────────────────────────────────────────────────
async def handle_unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🤔 Please send a valid video URL.\n"
        "Type /help for instructions."
    )


# ── Main ────────────────────────────────────────────────────────────────────────
def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(
        MessageHandler(filters.TEXT & filters.Regex(r"https?://"), handle_url)
    )
    app.add_handler(CallbackQueryHandler(handle_quality_selection, pattern=r"^dl\|"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_unknown))

    logger.info("Bot is running. Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
