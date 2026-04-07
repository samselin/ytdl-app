#!/bin/bash
echo ""
echo "  ╔══════════════════════════════╗"
echo "  ║   YTDL — by SamZ GFX  🎬    ║"
echo "  ╚══════════════════════════════╝"
echo ""

# Check Python
if ! command -v python3 &>/dev/null; then
  echo "  ✗ Python3 not found. Please install Python 3.8+"
  exit 1
fi

# Install deps
echo "  → Installing dependencies..."
pip3 install -r requirements.txt -q

# Check ffmpeg (needed for audio conversion)
if ! command -v ffmpeg &>/dev/null; then
  echo ""
  echo "  ⚠  ffmpeg not found — audio conversion may fail."
  echo "     Install with: brew install ffmpeg (Mac) / sudo apt install ffmpeg (Linux)"
  echo ""
fi

echo "  → Starting server at http://localhost:5000"
echo ""
python3 app.py
