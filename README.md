# 🎬 Telegram Video Downloader Bot

একটি শক্তিশালী Telegram বট যা YouTube, Facebook, Instagram, TikTok-সহ ১০০০+ সাইট থেকে ভিডিও ডাউনলোড করে পাঠাতে পারে।

---

## 📁 Project Structure

```
telegram-downloader-bot/
├── bot.py            # Main bot logic & Telegram handlers
├── downloader.py     # yt-dlp wrapper (metadata + download)
├── requirements.txt  # Python dependencies
├── .env.example      # Environment variable template
└── downloads/        # Temp folder (auto-created, auto-cleaned)
```

---

## ⚙️ Setup & Installation

### 1. Clone / copy the project
```bash
cd telegram-downloader-bot
```

### 2. Create a virtual environment
```bash
python -m venv venv
source venv/bin/activate        # Linux / macOS
venv\Scripts\activate.bat       # Windows
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Create your `.env` file
```bash
cp .env.example .env
```
Edit `.env` and paste your Bot Token from [@BotFather](https://t.me/BotFather):
```
BOT_TOKEN=123456789:ABCDefgh...
```

### 5. (Optional) Install FFmpeg — required for merging video+audio
```bash
# Ubuntu / Debian
sudo apt install ffmpeg

# macOS (Homebrew)
brew install ffmpeg

# Windows — download from https://ffmpeg.org/download.html and add to PATH
```

### 6. Run the bot
```bash
python bot.py
```

---

## 🤖 Bot Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message |
| `/help`  | Usage instructions |
| _(any URL)_ | Analyse and show quality options |

---

## 🔒 Notes

- Telegram has a **2 GB** file upload limit per message.
- Downloaded files are **automatically deleted** after sending.
- Private/login-required videos cannot be downloaded.
