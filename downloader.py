import os
import re
import asyncio
import shutil
import urllib.request
from pathlib import Path
import yt_dlp
from config import DOWNLOAD_DIR, MAX_FILE_SIZE_MB

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None
YTDL_OPTS = {
    "outtmpl": os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s"),
    "quiet": True,
    "no_warnings": True,
    "extract_flat": False,
    "retries": 10,
    "fragment_retries": 10,
    "extractor_args": {"youtube": {"skip": ["dash", "hls"]}},
}

def cleanup_temp_files():
    for f in os.listdir(DOWNLOAD_DIR):
        try:
            os.remove(os.path.join(DOWNLOAD_DIR, f))
        except Exception:
            pass

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

def get_media_type(filepath: str) -> str:
    ext = Path(filepath).suffix.lower()
    if ext in (".mp4", ".webm", ".mkv", ".avi", ".mov"):
        return "video"
    if ext in (".mp3", ".m4a", ".ogg", ".wav", ".flac", ".aac", ".opus"):
        return "audio"
    if ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"):
        return "photo"
    return "document"

def _find_file(base_path: str) -> str | None:
    fp = base_path
    if os.path.exists(fp):
        return fp
    stem = Path(fp).stem
    for f in os.listdir(DOWNLOAD_DIR):
        if f.startswith(stem):
            return os.path.join(DOWNLOAD_DIR, f)
    return None

async def extract_info(url: str) -> dict | None:
    loop = asyncio.get_event_loop()
    def _fetch():
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "extract_flat": False}) as ydl:
            return ydl.extract_info(url, download=False)
    try:
        return await loop.run_in_executor(None, _fetch)
    except Exception as e:
        print(f"Ошибка получения информации: {e}")
        return None

async def download_media(url: str) -> str | None:
    loop = asyncio.get_event_loop()
    opts = {**YTDL_OPTS, "format": "bv*+ba/b", "merge_output_format": "mp4"}

    def _dl():
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return ydl.prepare_filename(info)

    try:
        fp = await loop.run_in_executor(None, _dl)
        return _find_file(fp)
    except Exception as e:
        print(f"Ошибка скачивания: {e}")
        return None

async def download_audio_only(url: str) -> str | None:
    loop = asyncio.get_event_loop()
    opts = {**YTDL_OPTS}
    if FFMPEG_AVAILABLE:
        opts["format"] = "bestaudio/best"
        opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}]
    else:
        opts["format"] = "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio"

    def _dl():
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            base = ydl.prepare_filename(info)
            return Path(base).stem + ".mp3" if FFMPEG_AVAILABLE else base

    try:
        fp = await loop.run_in_executor(None, _dl)
        return _find_file(fp)
    except Exception as e:
        print(f"Ошибка скачивания аудио: {e}")
        return None

async def download_slideshow(url: str) -> list[str]:
    loop = asyncio.get_event_loop()
    def _dl():
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "extract_flat": False}) as ydl:
            info = ydl.extract_info(url, download=False)
        if info.get("_type") != "playlist" or not info.get("entries"):
            return []
        images = []
        for entry in info["entries"]:
            img_url = entry.get("url") or entry.get("thumbnail_url") or ""
            if not img_url:
                continue
            ext = img_url.rsplit(".", 1)[-1].split("?")[0][:4] or "jpg"
            filename = f"slide_{entry.get('id', 'img')}.{ext}"
            filepath = os.path.join(DOWNLOAD_DIR, filename)
            try:
                urllib.request.urlretrieve(img_url, filepath)
                if os.path.exists(filepath):
                    images.append(filepath)
            except Exception as e:
                print(f"Ошибка скачивания слайда: {e}")
        return images
    try:
        return await loop.run_in_executor(None, _dl)
    except Exception as e:
        print(f"Ошибка загрузки слайд-шоу: {e}")
        return []

def check_file_size(filepath: str) -> bool:
    size_mb = os.path.getsize(filepath) / (1024 * 1024)
    return size_mb <= MAX_FILE_SIZE_MB

def cleanup(filepath: str):
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
    except Exception:
        pass
