# YTDL — YouTube Downloader
**by SamZ GFX**

Download YouTube videos and audio from a slick local web interface.

## Requirements
- Python 3.8+
- ffmpeg (for audio/MP3 conversion)
  - Mac: `brew install ffmpeg`
  - Linux: `sudo apt install ffmpeg`
  - Windows: https://ffmpeg.org/download.html

## Run

**Mac / Linux:**
```bash
chmod +x run.sh
./run.sh
```

**Windows:**
Double-click `run.bat`

Then open **http://localhost:5000** in your browser.

## Features
- Paste any YouTube URL → fetch video info + thumbnail
- Choose Audio (MP3) or Video (MP4) formats
- Real-time download progress bar
- One-click file save

---
*Built with Flask + yt-dlp*
