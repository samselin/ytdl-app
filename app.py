from flask import Flask, render_template, request, jsonify, send_file, Response
import yt_dlp
import os
import json
import threading
import uuid
import glob
import time
import re
import subprocess
import shutil

app = Flask(__name__)
DOWNLOAD_DIR = os.path.join(os.path.dirname(__file__), "static", "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# --- Auto-discover FFmpeg ---
def find_ffmpeg():
    """Search for ffmpeg.exe in PATH and common Windows install locations."""
    # 1. Check PATH first
    found = shutil.which("ffmpeg")
    if found and os.name != 'nt':
        # On Linux/PaaS, if it's in PATH, just return the path to the executable's dir
        return os.path.dirname(os.path.abspath(found))
    
    if found and os.name == 'nt':
        return os.path.dirname(os.path.abspath(found))

    # 2. Search common Windows install directories
    home = os.path.expanduser("~")
    search_patterns = [
        # WinGet installs (specifically Gyann.FFmpeg which is common)
        os.path.join(home, "AppData", "Local", "Microsoft", "WinGet", "Packages", "Gyan.FFmpeg*", "**", "bin", "ffmpeg.exe"),
        os.path.join(home, "AppData", "Local", "Microsoft", "WinGet", "Packages", "*ffmpeg*", "**", "ffmpeg.exe"),
        # Common manual installs
        "C:\\ffmpeg\\bin\\ffmpeg.exe",
        "C:\\ffmpeg\\ffmpeg.exe",
        # Program Files
        "C:\\Program Files\\ffmpeg\\bin\\ffmpeg.exe",
        "C:\\Program Files (x86)\\ffmpeg\\bin\\ffmpeg.exe",
    ]

    for pattern in search_patterns:
        try:
            matches = glob.glob(pattern, recursive=True)
            if matches:
                return os.path.dirname(os.path.abspath(matches[0]))
        except Exception as e:
            print(f"Error searching pattern {pattern}: {e}")

    return None

FFMPEG_DIR = find_ffmpeg()
HAS_FFMPEG = FFMPEG_DIR is not None

if HAS_FFMPEG:
    print(f"✅ FFmpeg found at: {FFMPEG_DIR}")
    # Add FFMPEG_DIR to the subprocess environment just in case
    os.environ["PATH"] = FFMPEG_DIR + os.pathsep + os.environ.get("PATH", "")
else:
    print("⚠️  FFmpeg not found. Audio format conversion and high-res video will be unavailable.")

# Track job progress with type-safe initialization
# Status can be: 'pending', 'downloading', 'done', 'error'
jobs = {}

def get_ydl_cookies():
    """Check for a local cookies.txt file for cloud environments."""
    cookie_path = os.path.join(os.path.dirname(__file__), "cookies.txt")
    if os.path.exists(cookie_path):
        return {"cookiefile": cookie_path}
    # Fallback to browser only if on Windows/Local
    if os.name == 'nt':
        return {"cookiesfrombrowser": ("edge",)}
    return {}

def get_info(url):
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "nocheckcertificate": True,
        **get_ydl_cookies(),
        "format": "bestvideo+bestaudio/best" if HAS_FFMPEG else "best",
        "extractor_args": {
            "youtube": {
                "player_client": ["tv_embedded", "ios", "web"],
                "player_skip": ["webpage", "configs"],
            }
        },
        "http_headers": {
            "User-Agent": "com.google.ios.youtube/19.29.1 (iPhone16,2; U; CPU iOS 17_5_1 like Mac OS X)",
            "Accept-Language": "en-US,en;q=0.9",
        },
    }
    if FFMPEG_DIR:
        ydl_opts["ffmpeg_location"] = FFMPEG_DIR
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        formats = []
        seen = set()
        
        # Add 'Best' options
        formats.append({
            "id": "bestvideo+bestaudio/best" if HAS_FFMPEG else "best",
            "label": "Best Quality (Auto)" + ("" if HAS_FFMPEG else " - Limited No FFmpeg"),
            "type": "video",
            "height": 9999
        })

        # Group video formats by standard resolution categories
        def get_res_label(h):
            if h > 1620: return ("4K (2160p)", 2160)
            if h > 1260: return ("2K (1440p)", 1440)
            if h > 900:  return ("1080p", 1080)
            if h > 600:  return ("720p", 720)
            if h > 420:  return ("480p", 480)
            if h > 300:  return ("360p", 360)
            if h > 180:  return ("240p", 240)
            return (f"{h}p", h)

        res_map = {}
        for f in info.get("formats", []):
            if f.get("vcodec") != "none":
                h = f.get("height", 0)
                if not h: continue
                
                label, target_h = get_res_label(h)
                # Keep the best bitrate format for each standard resolution label
                if label not in res_map or (f.get("vbr", 0) or 0) > (res_map[label]["f"].get("vbr", 0) or 0):
                    res_map[label] = {"f": f, "height": h, "label": label}

        # Sort resolutions: 4K down to 144p
        sorted_labels = sorted(res_map.keys(), 
                               key=lambda l: res_map[l]["height"], 
                               reverse=True)
                               
        for label in sorted_labels:
            item = res_map[label]
            formats.append({
                "id": f"res_{item['height']}", # Pass actual pixel height for targeting
                "label": label + (" HD" if item['height'] >= 720 else ""),
                "type": "video",
                "height": item['height']
            })
        
        if HAS_FFMPEG:
            audio_formats = [
                {"id": "bestaudio/best", "label": "MP3 — 192 kbps",      "type": "audio", "height": 9999, "codec": "mp3"},
                {"id": "bestaudio/best", "label": "M4A — AAC (iTunes)",   "type": "audio", "height": 9998, "codec": "m4a"},
                {"id": "bestaudio/best", "label": "AAC — Raw AAC",        "type": "audio", "height": 9997, "codec": "aac"},
                {"id": "bestaudio/best", "label": "OGG Vorbis",           "type": "audio", "height": 9996, "codec": "vorbis"},
                {"id": "bestaudio/best", "label": "Opus — High Efficiency","type": "audio", "height": 9995, "codec": "opus"},
                {"id": "bestaudio/best", "label": "FLAC — Lossless",      "type": "audio", "height": 9994, "codec": "flac"},
                {"id": "bestaudio/best", "label": "WAV — Uncompressed",   "type": "audio", "height": 9993, "codec": "wav"},
            ]
        else:
            audio_formats = [
                {"id": "bestaudio/best", "label": "Best Audio (no FFmpeg)", "type": "audio", "height": 9999, "codec": "none"},
            ]
        
        formats = sorted(formats, key=lambda x: x["height"], reverse=True)
        all_formats = audio_formats + formats
        return {
            "title": str(info.get("title", "Unknown")),
            "thumbnail": str(info.get("thumbnail", "")),
            "duration": str(info.get("duration_string", "0:00")),
            "channel": str(info.get("channel", "Unknown")),
            "views": f"{info.get('view_count', 0):,}" if info.get("view_count") else "N/A",
            "formats": all_formats
        }

# Map codec names to FFmpeg output extensions
CODEC_EXT_MAP = {
    "mp3":    "mp3",
    "m4a":    "m4a",
    "aac":    "aac",
    "vorbis": "ogg",
    "opus":   "opus",
    "flac":   "flac",
    "wav":    "wav",
}

def run_download(job_id, url, fmt_id, is_audio, audio_codec="mp3"):
    try:
        jobs[job_id] = {"status": "downloading", "progress": 0, "filename": "", "error": ""}

        def progress_hook(d):
            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 1
                downloaded = d.get("downloaded_bytes", 0)
                jobs[job_id]["progress"] = min(int(downloaded / total * 90), 90)
            elif d["status"] == "finished":
                jobs[job_id]["progress"] = 95

        # Sanitize fmt_id to string
        fmt_id = str(fmt_id)
        out_template = os.path.join(DOWNLOAD_DIR, f"{job_id}_%(title).100s.%(ext)s")

        ydl_opts = {
            "outtmpl": out_template,
            "progress_hooks": [progress_hook],
            "quiet": True,
            "no_warnings": True,
            "restrictfilenames": True,
            "windowsfilenames": True,
            "noprogress": True,
            "writethumbnail": True,
            "nocheckcertificate": True,
            "prefer_ffmpeg": True,
            "socket_timeout": 60,
            "retries": 10,
            "cachedir": False,
            "noplaylist": True,
            **get_ydl_cookies(),
            "extractor_args": {
                "youtube": {
                    "player_client": ["tv_embedded", "ios", "web"],
                    "player_skip": ["webpage", "configs"],
                }
            },
            "http_headers": {
                "User-Agent": "com.google.ios.youtube/19.29.1 (iPhone16,2; U; CPU iOS 17_5_1 like Mac OS X)",
                "Accept-Language": "en-US,en;q=0.9",
            },
        }

        if FFMPEG_DIR:
            ydl_opts["ffmpeg_location"] = FFMPEG_DIR

        if is_audio:
            ydl_opts["format"] = fmt_id
            if HAS_FFMPEG and audio_codec != "none":
                ydl_opts["postprocessors"] = [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": audio_codec,
                        "preferredquality": "0" if audio_codec == "flac" else "192",
                    },
                    {
                        "key": "FFmpegThumbnailsConvertor",
                        "format": "jpg",
                    },
                    {
                        "key": "EmbedThumbnail", 
                    },
                    {
                        "key": "FFmpegMetadata",
                        "add_metadata": True,
                    }
                ]
                # Force-clear problematic tags (privacy protection)
                # and add custom branding tags
                ydl_opts["postprocessor_args"] = [
                    "-metadata", "album=YTDL",
                    "-metadata", "description=", 
                    "-metadata", "comment=Downloaded via YTDL",
                ]
        else:
            # Construct a robust format quality query
            try:
                if str(fmt_id).startswith("res_"):
                    # Use resolution targeting (the most robust way)
                    h = fmt_id.split("_")[1]
                    # We use bestvideo[height<=H] to get the best one for that resolution
                    fmt_str = f"bestvideo[height<={h}]+bestaudio/best"
                elif "bestvideo" in str(fmt_id):
                    fmt_str = str(fmt_id)
                elif str(fmt_id).isdigit():
                    # Pin to ID + best audio
                    fmt_str = f"{fmt_id}+bestaudio/best"
                else:
                    fmt_str = "bestvideo+bestaudio/best"
            except:
                fmt_str = "bestvideo+bestaudio/best"
            
            print(f"[DOWNLOAD] Job {job_id}: Resolved Format Query='{fmt_str}'")
            ydl_opts["format"] = fmt_str
            if HAS_FFMPEG:
                # Merge into robust container (mkv handles VP9/Opus better than mp4 without re-encoding)
                ydl_opts["merge_output_format"] = "mkv"

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                ydl.download([url])
            except Exception as ydl_err:
                # Manual Rescue for Windows Locking issues (WinError 32)
                print(f"yt-dlp reported error: {ydl_err}. Attempting manual rescue...")
                time.sleep(5) # Deep wait for Antivirus/OS to release locks
                
                # Try to manually finalize if .temp files exist
                temp_files = glob.glob(os.path.join(DOWNLOAD_DIR, f"{job_id}_*.temp*"))
                if temp_files:
                    # Sort candidates by size (Largest is usually the video)
                    temp_files.sort(key=os.path.getsize, reverse=True)
                    best_candidate = temp_files[0]
                    final_path = best_candidate.replace(".temp", "").split(".f")[0] + os.path.splitext(best_candidate)[1].replace(".temp", "")
                    try:
                        import shutil
                        shutil.move(best_candidate, final_path)
                        print(f"🚀 Rescue Successful! Moved {best_candidate} -> {final_path}")
                    except Exception as rescue_err:
                        print(f"Rescue failed: {rescue_err}")                
        # Windows settle time for FS renames
        time.sleep(2)
        
        # Determine expected extension for better identification
        expected_ext = CODEC_EXT_MAP.get(audio_codec) if is_audio else None
        
        # Look for the final file
        all_files = glob.glob(os.path.join(DOWNLOAD_DIR, f"{job_id}_*"))
        # Filter out temp/metadata files
        valid_files = [f for f in all_files if not f.endswith(('.part', '.temp', '.ytdl', '.webp', '.jpg', '.png', '.json', '.xml'))]
        
        final_file = None
        if valid_files:
            if expected_ext:
                # Prioritize file with expected extension
                for f in valid_files:
                    if f.endswith(f".{expected_ext}"):
                        final_file = f
                        break
            
            if not final_file:
                # Fallback: Pick the largest file (usually movie/audio vs small metadata)
                valid_files.sort(key=os.path.getsize, reverse=True)
                final_file = valid_files[0]

        if final_file:
            jobs[job_id]["filename"] = os.path.basename(final_file)
            jobs[job_id]["status"] = "done"
            jobs[job_id]["progress"] = 100
            print(f"[SUCCESS] Job {job_id} saved as: {jobs[job_id]['filename']}")
        else:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = "File not found after download completion"
    except Exception as e:
        import traceback
        traceback.print_exc()
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = str(e)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/info", methods=["POST"])
def info():
    url = request.json.get("url", "") if request.json else ""
    if not url:
        return jsonify({"ok": False, "error": "No URL provided"})
    try:
        data = get_info(url)
        return jsonify({"ok": True, "data": data})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route("/download", methods=["POST"])
def download():
    if not request.json:
        return jsonify({"ok": False, "error": "No data provided"})
        
    url = request.json.get("url", "")
    fmt_id = request.json.get("format_id", "best")
    is_audio = request.json.get("is_audio", False)
    audio_codec = request.json.get("audio_codec", "mp3")
    
    if not url:
        return jsonify({"ok": False, "error": "No URL provided"})

    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {"status": "pending", "progress": 0, "filename": "", "error": ""}
    
    t = threading.Thread(target=run_download, args=(job_id, url, fmt_id, is_audio, audio_codec))
    t.daemon = True
    t.start()
    return jsonify({"ok": True, "job_id": job_id})

@app.route("/progress/<job_id>")
def progress(job_id):
    def generate():
        while True:
            job = jobs.get(job_id, {"status": "error", "error": "Job not found"})
            yield f"data: {json.dumps(job)}\n\n"
            if job.get("status") in ("done", "error"):
                break
            time.sleep(0.5)
    return Response(generate(), mimetype="text/event-stream")

@app.route("/file/<job_id>")
def serve_file(job_id):
    job = jobs.get(job_id, {})
    filename = str(job.get("filename", ""))
    if not filename:
        return "Not found", 404
    filepath = os.path.join(DOWNLOAD_DIR, filename)
    
    display_name = filename.split("_", 1)[-1] if "_" in filename else filename
    response = send_file(filepath, as_attachment=True, download_name=display_name)
    
    @response.call_on_close
    def remove_file():
        try:
            # Short wait for file handle release on Windows
            time.sleep(1)
            os.remove(filepath)
            print(f"🗑️ Cleaned up downloaded file: {filename}")
        except Exception as e:
            print(f"Cleanup skip for {filename}: {e}")
            
    return response

@app.route("/status")
def status():
    return jsonify({
        "ffmpeg_present": HAS_FFMPEG,
        "ffmpeg_dir": FFMPEG_DIR,
        "ffmpeg_version": subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True).stdout.split("\n")[0] if HAS_FFMPEG else "N/A"
    })

# --- Background Cleanup Thread ---
def cleanup_thread():
    """Delete old files every 10 minutes (files older than 20 min)."""
    while True:
        try:
            now = time.time()
            if os.path.exists(DOWNLOAD_DIR):
                for f in os.listdir(DOWNLOAD_DIR):
                    path = os.path.join(DOWNLOAD_DIR, f)
                    if os.path.isfile(path):
                        mtime = os.path.getmtime(path)
                        # Remove if older than 20 minutes
                        if now - mtime > 1200: 
                            try:
                                os.remove(path)
                                print(f"🧹 GC: Removed old file {f}")
                            except:
                                pass
        except Exception as e:
            print(f"Cleanup error: {e}")
        time.sleep(600)

if __name__ == "__main__":
    t = threading.Thread(target=cleanup_thread, daemon=True)
    t.start()
    
    port = int(os.environ.get("PORT", 7860))
    print(f"\n🎬 YTDL online at http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=True)