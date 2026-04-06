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
    raise EnvironmentError("BOT_TOKEN is not set in the .env file.")

# Telegram hard limit for bot uploads
MAX_FILE_SIZE_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB


# ── /start command ──────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a welcome message."""
    await update.message.reply_text(
        "👋 *Welcome to Video Downloader Bot!*\n\n"
        "📎 Just send me a video link from:\n"
        "  • YouTube  🎬\n"
        "  • Facebook 📘\n"
        "  • Instagram 📷\n"
        "  • TikTok, Twitter, and 1000+ sites\n\n"
        "I'll show available qualities — pick one and I'll send the file! 🚀",
        parse_mode="Markdown",
    )


# ── /help command ───────────────────────────────────────────────────────────────
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a help message."""
    await update.message.reply_text(
        "ℹ️ *How to use:*\n\n"
        "1. Paste any supported video URL\n"
        "2. Choose your preferred quality\n"
        "3. Wait while I download & send the file\n\n"
        "⚠️ Files larger than *2 GB* cannot be sent via Telegram.",
        parse_mode="Markdown",
    )


# ── URL handler ─────────────────────────────────────────────────────────────────
async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Receives a URL, extracts available formats via yt-dlp,
    and presents an inline keyboard for quality selection.
    """
    url = update.message.text.strip()
    status_msg = await update.message.reply_text("🔍 Analysing link, please wait…")

    try:
        formats = await asyncio.get_event_loop().run_in_executor(
            None, extract_formats, url
        )
    except ValueError as exc:
        await status_msg.edit_text(f"❌ *Error:* {exc}", parse_mode="Markdown")
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

    # ── Build inline keyboard ──────────────────────────────────────────────────
    keyboard: list[list[InlineKeyboardButton]] = []

    for fmt in formats:
        label = fmt["label"]          # e.g. "720p  (~45 MB)"
        callback = fmt["callback"]    # e.g. "dl|<url>|720p|bestvideo..."
        keyboard.append([InlineKeyboardButton(label, callback_data=callback)])

    # Store the original URL in user_data so callback can retrieve it
    context.user_data["pending_url"] = url

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
    """
    Triggered when the user taps a quality button.
    Downloads the file and sends it back.
    """
    query = update.callback_query
    await query.answer()  # acknowledge the tap immediately

    # callback_data format: "dl|<video_id>|<audio_id>|<url>"
    try:
        _, video_id, audio_id, url = query.data.split("|", 3)
    except ValueError:
        await query.edit_message_text("❌ Invalid selection. Please try again.")
        return

    await query.edit_message_text(
        f"⬇️ Downloading… this may take a moment."
    )

    # ── Download ───────────────────────────────────────────────────────────────
    try:
        file_path, file_size = await asyncio.get_event_loop().run_in_executor(
            None, download_media, url, video_id, audio_id
        )
    except FileNotFoundError as exc:
        await query.edit_message_text(f"❌ Download failed: {exc}")
        return
    except Exception as exc:
        logger.exception("Download error")
        await query.edit_message_text(f"❌ Unexpected error during download: {exc}")
        return

    # ── Size check ─────────────────────────────────────────────────────────────
    if file_size > MAX_FILE_SIZE_BYTES:
        os.remove(file_path)
        await query.edit_message_text(
            "❌ *File too large!*\n"
            f"The file is `{file_size / (1024**3):.2f} GB`, "
            "but Telegram only allows up to *2 GB*.",
            parse_mode="Markdown",
        )
        return

    # ── Send file ──────────────────────────────────────────────────────────────
    await query.edit_message_text("📤 Uploading to Telegram…")

    try:
        if file_path.endswith(".mp3"):
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
        # ── Cleanup: delete local file regardless of outcome ───────────────────
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info("Cleaned up: %s", file_path)


# ── Unknown message handler ─────────────────────────────────────────────────────
async def handle_unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Prompt the user to send a valid URL."""
    await update.message.reply_text(
        "🤔 Please send a valid video URL.\n"
        "Type /help for instructions."
    )


# ── Main ────────────────────────────────────────────────────────────────────────
def main() -> None:
    """Build and run the bot application."""
    app = Application.builder().token(BOT_TOKEN).build()

    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))

    # URL message handler — matches any text that looks like a URL
    app.add_handler(
        MessageHandler(filters.TEXT & filters.Regex(r"https?://"), handle_url)
    )

    # Inline keyboard callback
    app.add_handler(CallbackQueryHandler(handle_quality_selection, pattern=r"^dl\|"))

    # Fallback for unrecognised messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_unknown))

    logger.info("Bot is running. Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
