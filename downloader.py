import os
import re
import asyncio
import shutil
from pathlib import Path
import yt_dlp
from config import DOWNLOAD_DIR, MAX_FILE_SIZE_MB

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

def cleanup_temp_files():
    for f in os.listdir(DOWNLOAD_DIR):
        try:
            os.remove(os.path.join(DOWNLOAD_DIR, f))
        except Exception:
            pass

def sanitize(text: str) -> str:
    text = re.sub(r'[<>:"/\\|?*]', "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:100] or "video"

def detect_platform(url: str) -> str:
    if re.search(r"(tiktok\.com|vm\.tiktok\.)", url, re.IGNORECASE):
        return "tiktok"
    elif re.search(r"(youtube\.com|youtu\.be)", url, re.IGNORECASE):
        return "youtube"
    elif re.search(r"(instagram\.com|instagr\.am)", url, re.IGNORECASE):
        return "instagram"
    elif re.search(r"(pinterest\.com|pin\.it)", url, re.IGNORECASE):
        return "pinterest"
    return "unknown"

def get_ydl_opts(format_type: str = "video") -> dict:
    base = {
        "outtmpl": os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
    }

    if format_type == "video":
        base["format"] = "best[ext=mp4]/best"
        base["merge_output_format"] = "mp4"
    elif format_type == "audio":
        base["format"] = "bestaudio/best"
        base["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]

    return base

async def get_video_info(url: str) -> dict:
    loop = asyncio.get_event_loop()

    def _fetch():
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
            return ydl.extract_info(url, download=False)

    info = await loop.run_in_executor(None, _fetch)

    return {
        "title": info.get("title", "Без названия"),
        "duration": info.get("duration", 0),
        "platform": detect_platform(url),
        "url": url,
    }

async def download_video(url: str) -> str | None:
    loop = asyncio.get_event_loop()
    opts = get_ydl_opts("video")

    def _download():
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return ydl.prepare_filename(info)

    try:
        filepath = await loop.run_in_executor(None, _download)

        ext = Path(filepath).suffix
        if ext not in (".mp4", ".webm", ".mkv"):
            base = Path(filepath).stem
            mp4_path = os.path.join(DOWNLOAD_DIR, f"{base}.mp4")
            if os.path.exists(mp4_path):
                filepath = mp4_path

        if not os.path.exists(filepath):
            for f in os.listdir(DOWNLOAD_DIR):
                if f.startswith(Path(filepath).stem):
                    filepath = os.path.join(DOWNLOAD_DIR, f)
                    break

        return filepath if os.path.exists(filepath) else None
    except Exception as e:
        print(f"Ошибка скачивания видео: {e}")
        return None

async def download_audio(url: str) -> str | None:
    loop = asyncio.get_event_loop()
    opts = get_ydl_opts("audio")

    def _download():
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            base = ydl.prepare_filename(info)
            return Path(base).stem + ".mp3"

    try:
        filename = await loop.run_in_executor(None, _download)
        filepath = os.path.join(DOWNLOAD_DIR, filename)

        if not os.path.exists(filepath):
            for f in os.listdir(DOWNLOAD_DIR):
                if f.startswith(Path(filename).stem):
                    filepath = os.path.join(DOWNLOAD_DIR, f)
                    break

        return filepath if os.path.exists(filepath) else None
    except Exception as e:
        print(f"Ошибка скачивания аудио: {e}")
        return None

def check_file_size(filepath: str) -> bool:
    size_mb = os.path.getsize(filepath) / (1024 * 1024)
    return size_mb <= MAX_FILE_SIZE_MB

def cleanup(filepath: str):
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
    except Exception:
        pass
