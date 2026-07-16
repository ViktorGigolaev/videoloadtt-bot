import os
import re
import json
import asyncio
import shutil
import urllib.request
from pathlib import Path
import yt_dlp
from config import DOWNLOAD_DIR, MAX_FILE_SIZE_MB, COOKIES_FILE

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

def _find_ffmpeg():
    if shutil.which("ffmpeg") is not None:
        return True
    script_dir = os.path.dirname(os.path.abspath(__file__))
    for d in (script_dir, DOWNLOAD_DIR):
        fp = os.path.join(d, "ffmpeg.exe")
        if os.path.exists(fp):
            os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
            return True
    return False

FFMPEG_AVAILABLE = _find_ffmpeg()

YTDL_OPTS = {
    "outtmpl": os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s"),
    "quiet": True,
    "no_warnings": True,
    "extract_flat": False,
    "retries": 10,
    "fragment_retries": 10,
    "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
    "throttledratelimit": 1000000,
}

if COOKIES_FILE and os.path.exists(COOKIES_FILE):
    YTDL_OPTS["cookiefile"] = COOKIES_FILE

SLIDESHOW_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "retries": 10,
    "fragment_retries": 10,
    "outtmpl": os.path.join(DOWNLOAD_DIR, "%(id)s.%(ext)s"),
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
    elif re.search(r"(pinterest\.[a-z]+|pin\.it)", url, re.IGNORECASE):
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

def is_gif(filepath: str) -> bool:
    return Path(filepath).suffix.lower() == ".gif"

def _find_file(base_path: str) -> str | None:
    if base_path and os.path.exists(base_path):
        return base_path
    if not base_path:
        return None
    stem = Path(base_path).stem
    for f in os.listdir(DOWNLOAD_DIR):
        if f.startswith(stem) or stem.startswith(f):
            return os.path.join(DOWNLOAD_DIR, f)
    return None

async def extract_info(url: str) -> dict | None:
    loop = asyncio.get_event_loop()
    def _fetch():
        with yt_dlp.YoutubeDL({**YTDL_OPTS, "extract_flat": False}) as ydl:
            return ydl.extract_info(url, download=False)
    try:
        return await loop.run_in_executor(None, _fetch)
    except Exception as e:
        print(f"extract_info error: {e}")
        return None

async def download_tiktok_photos(raw_url: str) -> list[str]:
    """Download photos from TikTok photo posts using TikTok API"""
    try:
        import requests
    except ImportError:
        return []
    from urllib.parse import urlparse, parse_qs
    url = raw_url.strip()
    loop = asyncio.get_event_loop()
    def _dl():
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.tiktok.com/",
            "Origin": "https://www.tiktok.com",
        }
        parsed = urlparse(url)
        path = parsed.path
        item_id = None
        m_id = re.search(r"/(?:photo|video|note)/(\d+)", path)
        if m_id:
            item_id = m_id.group(1)
        if not item_id:
            qs = parse_qs(parsed.query)
            if "item_id" in qs:
                item_id = qs["item_id"][0]
        if not item_id:
            m_id = re.search(r"(\d{15,})", parsed.path)
            if m_id:
                item_id = m_id.group(1)
        if not item_id:
            m_id = re.search(r"tiktok\.com/.*?(\d{15,})", url)
            if m_id:
                item_id = m_id.group(1)
        if item_id:
            api_url = f"https://www.tiktok.com/api/item/detail/?item_id={item_id}&from_page=photo&region=US"
            try:
                resp = requests.get(api_url, headers=headers, timeout=30)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                print(f"TikTok API error: {e}")
                data = None
            if data:
                item = data.get("itemInfo", {}).get("itemStruct") or data.get("itemInfo", {}).get("item") or data
                if item:
                    image_post = item.get("imagePost")
                    if image_post:
                        images_data = image_post.get("images", [])
                        if images_data:
                            result = []
                            for i, img in enumerate(images_data):
                                url_list = None
                                if isinstance(img, dict):
                                    iu = img.get("imageURL", img)
                                    if isinstance(iu, dict):
                                        url_list = iu.get("urlList", [])
                                if not url_list:
                                    continue
                                img_url = url_list[0]
                                ext = img_url.rsplit(".", 1)[-1].split("?")[0][:4] or "jpg"
                                if ext not in ("jpg", "jpeg", "png", "webp", "gif", "bmp"):
                                    ext = "jpg"
                                filepath = os.path.join(DOWNLOAD_DIR, f"tiktok_photo_{i}.{ext}")
                                try:
                                    r = requests.get(img_url, headers=headers, timeout=30)
                                    r.raise_for_status()
                                    with open(filepath, "wb") as f:
                                        f.write(r.content)
                                    if os.path.getsize(filepath) > 1024:
                                        result.append(filepath)
                                except Exception as e:
                                    print(f"TikTok photo {i} error: {e}")
                            if result:
                                return result
        return _download_tiktok_from_page(url, requests, headers)
    try:
        return await loop.run_in_executor(None, _dl)
    except Exception as e:
        print(f"download_tiktok_photos error: {e}")
        return []

def _download_tiktok_from_page(url: str, requests_mod, headers) -> list[str]:
    """Fallback: parse image URLs from TikTok page HTML (sync, runs in executor)"""
    try:
        resp = requests_mod.get(url, headers=headers, timeout=30)
        html = resp.text
    except Exception as e:
        print(f"TikTok page fetch error: {e}")
        return []
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        img_urls = []
        for tag in soup.find_all("img"):
            src = tag.get("src") or tag.get("data-src") or ""
            if "p16-" in src or "p9-" in src:
                img_urls.append(src.split("?")[0])
    except ImportError:
        img_urls = []
    if not img_urls:
        m_json = re.search(r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', html, re.DOTALL)
        if m_json:
            try:
                data = json.loads(m_json.group(1))
                raw = json.dumps(data)
                img_urls = re.findall(r'"urlList"\s*:\s*\["([^"]+)"', raw)
            except json.JSONDecodeError:
                pass
    if not img_urls:
        m_json = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
        if m_json:
            try:
                data = json.loads(m_json.group(1))
                raw = json.dumps(data)
                img_urls = re.findall(r'"urlList"\s*:\s*\["([^"]+)"', raw)
            except json.JSONDecodeError:
                pass
    if not img_urls:
        img_urls = re.findall(r'"image_url"\s*:\s*"([^"]+)"', html)
    if not img_urls:
        img_urls = re.findall(r'"urlList"\s*:\s*\["([^"]+)"', html)
    if not img_urls:
        img_urls = re.findall(r'"imageURL"\s*:\s*\{\s*"urlList"\s*:\s*\["([^"]+)"', html)
    if not img_urls:
        img_urls = re.findall(r'https?://[^"\'\s]+\.(?:jpg|jpeg|png|webp)[^"\'\s]*', html)
        img_urls = [u for u in img_urls if "p16-" in u or "p9-" in u or "p1-" in u]
    if not img_urls:
        print("TikTok: no image URLs found in page HTML")
        return []
    result = []
    for i, img_url in enumerate(set(img_urls)):
        img_url = img_url.replace("\\/", "/").replace("\\u0026", "&")
        ext = img_url.rsplit(".", 1)[-1].split("?")[0][:4] or "jpg"
        if ext not in ("jpg", "jpeg", "png", "webp", "gif", "bmp"):
            ext = "jpg"
        filepath = os.path.join(DOWNLOAD_DIR, f"tiktok_photo_{i}.{ext}")
        try:
            r = requests_mod.get(img_url, headers=headers, timeout=30)
            r.raise_for_status()
            with open(filepath, "wb") as f:
                f.write(r.content)
            if os.path.getsize(filepath) > 1024:
                result.append(filepath)
        except Exception as e:
            print(f"TikTok page photo {i} error: {e}")
    return result

async def download_media(url: str) -> str | None:
    loop = asyncio.get_event_loop()
    formats_to_try = [
        {"format": "bv*[height<=720][filesize<?50M]+ba/b[height<=720]/b", "merge_output_format": "mp4"},
        {"format": "bv*[filesize<?50M]+ba/b", "merge_output_format": "mp4"},
        {"format": "b[height<=720]/b", "merge_output_format": None},
        {"format": "b", "merge_output_format": None},
    ]
    for fmt_opts in formats_to_try:
        opts = {**YTDL_OPTS, **fmt_opts}
        opts = {k: v for k, v in opts.items() if v is not None}
        def _dl(o=opts):
            with yt_dlp.YoutubeDL(o) as ydl:
                info = ydl.extract_info(url, download=True)
                return ydl.prepare_filename(info)
        try:
            fp = await loop.run_in_executor(None, _dl)
            result = _find_file(fp)
            if result and os.path.getsize(result) > 1024:
                return result
        except Exception as e:
            print(f"download_media format error: {e}")
    return None

async def download_audio_only(url: str) -> str | None:
    loop = asyncio.get_event_loop()
    opts = {**YTDL_OPTS}
    if FFMPEG_AVAILABLE:
        opts["format"] = "bestaudio/best"
        opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}]
    else:
        opts["format"] = "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio"
    opts = {k: v for k, v in opts.items() if v is not None}
    def _dl(o=opts):
        with yt_dlp.YoutubeDL(o) as ydl:
            info = ydl.extract_info(url, download=True)
            base = ydl.prepare_filename(info)
            return Path(base).stem + ".mp3" if FFMPEG_AVAILABLE else base
    try:
        fp = await loop.run_in_executor(None, _dl)
        result = _find_file(fp)
        if result:
            return result
    except Exception as e:
        print(f"download_audio_only error: {e}")

    if not FFMPEG_AVAILABLE:
        return None

    video_opts = {k: v for k, v in {**YTDL_OPTS, "format": "best[ext=mp4]/best", "postprocessors": []}.items() if v is not None}
    def _dl_video():
        with yt_dlp.YoutubeDL(video_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return ydl.prepare_filename(info)
    try:
        fp = await loop.run_in_executor(None, _dl_video)
        video_path = _find_file(fp)
        if not video_path or not os.path.exists(video_path):
            return None
        audio_path = os.path.join(DOWNLOAD_DIR, Path(video_path).stem + ".mp3")
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-i", video_path, "-vn",
            "-acodec", "libmp3lame", "-ab", "192k",
            "-y", audio_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        cleanup(video_path)
        if os.path.exists(audio_path):
            return audio_path
    except Exception as e:
        print(f"download_audio_only (extract) error: {e}")
    return None

async def download_slideshow(url: str) -> list[str]:
    loop = asyncio.get_event_loop()
    def _dl():
        with yt_dlp.YoutubeDL({**SLIDESHOW_OPTS, "format": "best"}) as ydl:
            info = ydl.extract_info(url, download=True)
        if info.get("_type") != "playlist" or not info.get("entries"):
            return []
        result = []
        seen = set()
        for entry in info["entries"]:
            eid = entry.get("id", "")
            if not eid:
                continue
            for f in os.listdir(DOWNLOAD_DIR):
                fp = os.path.join(DOWNLOAD_DIR, f)
                if f.startswith(eid) and fp not in seen and os.path.isfile(fp):
                    seen.add(fp)
                    result.append(fp)
                    break
        if not result and not seen:
            for f in os.listdir(DOWNLOAD_DIR):
                fp = os.path.join(DOWNLOAD_DIR, f)
                if os.path.isfile(fp) and fp not in seen:
                    seen.add(fp)
                    result.append(fp)
        return result
    try:
        return await loop.run_in_executor(None, _dl)
    except Exception as e:
        print(f"download_slideshow error: {e}")
        return []

async def download_pinterest_content(url: str) -> str | None:
    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError:
        print("Pinterest: requests/bs4 not available, falling back to urllib")
        return await _download_pinterest_urllib(url)
    loop = asyncio.get_event_loop()
    def _dl():
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
            "Referer": "https://www.pinterest.com/",
        }
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            html = resp.text
        except Exception as e:
            print(f"Pinterest fetch error: {e}")
            return None
        soup = BeautifulSoup(html, "html.parser")
        meta_og_video = soup.find("meta", property="og:video")
        if meta_og_video and meta_og_video.get("content"):
            return None
        img_url = None
        meta_og_image = soup.find("meta", property="og:image")
        if meta_og_image:
            img_url = meta_og_image.get("content")
        if not img_url:
            meta_twitter = soup.find("meta", attrs={"name": "twitter:image"})
            if meta_twitter:
                img_url = meta_twitter.get("content")
        if not img_url:
            for script in soup.find_all("script", type="application/ld+json"):
                try:
                    data = json.loads(script.string or "{}")
                    for key in ("image", "thumbnailUrl"):
                        val = data.get(key)
                        if isinstance(val, str) and val.startswith("http"):
                            img_url = val.split("?")[0]
                            break
                        if isinstance(val, dict):
                            u = val.get("url") or val.get("contentUrl")
                            if u and str(u).startswith("http"):
                                img_url = str(u).split("?")[0]
                                break
                except json.JSONDecodeError:
                    pass
                if img_url:
                    break
        if not img_url:
            pin_img = soup.find("img", attrs={"data-test-id": "pin-image"})
            if pin_img:
                img_url = pin_img.get("src")
        if not img_url:
            m = re.search(r'"image_medium_url"\s*:\s*"([^"]+)"', html)
            if m:
                img_url = m.group(1).replace("\\/", "/")
        if not img_url:
            m = re.search(r'"image_original_url"\s*:\s*"([^"]+)"', html)
            if m:
                img_url = m.group(1).replace("\\/", "/")
        if not img_url:
            m = re.search(r'"url"\s*:\s*"([^"]+)"', html)
            if m:
                candidate = m.group(1).replace("\\/", "/")
                if "pinimg.com" in candidate:
                    img_url = candidate
        if not img_url:
            print("Pinterest: no image URL found in page")
            return None
        ext = img_url.rsplit(".", 1)[-1].split("?")[0][:4] or "jpg"
        if ext not in ("jpg", "jpeg", "png", "webp", "gif", "bmp"):
            ext = "jpg"
        filepath = os.path.join(DOWNLOAD_DIR, "pinterest_img." + ext)
        try:
            img_resp = requests.get(img_url, headers=headers, timeout=30)
            img_resp.raise_for_status()
            with open(filepath, "wb") as f:
                f.write(img_resp.content)
            if os.path.getsize(filepath) > 1024:
                return filepath
        except Exception:
            pass
        return None
    try:
        return await loop.run_in_executor(None, _dl)
    except Exception as e:
        print(f"download_pinterest_content error: {e}")
        return None

async def _download_pinterest_urllib(url: str) -> str | None:
    loop = asyncio.get_event_loop()
    def _dl():
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"},
        )
        try:
            resp = urllib.request.urlopen(req, timeout=30)
            html = resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            print(f"Pinterest urllib fetch error: {e}")
            return None
        if re.search(r'<meta[^>]+property="og:video"[^>]+content="\S+"', html):
            return None
        img_url = None
        m = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html)
        if m:
            img_url = m.group(1)
        if not img_url:
            m = re.search(r'<meta[^>]+name="twitter:image"[^>]+content="([^"]+)"', html)
            if m:
                img_url = m.group(1)
        if not img_url:
            m = re.search(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', html, re.DOTALL)
            if m:
                try:
                    data = json.loads(m.group(1))
                    for key in ("image", "thumbnailUrl"):
                        val = data.get(key)
                        if isinstance(val, str) and val.startswith("http"):
                            img_url = val.split("?")[0]
                            break
                        if isinstance(val, dict):
                            u = val.get("url") or val.get("contentUrl")
                            if u and str(u).startswith("http"):
                                img_url = str(u).split("?")[0]
                                break
                except json.JSONDecodeError:
                    pass
        if not img_url:
            m = re.search(r'"image_medium_url"\s*:\s*"([^"]+)"', html)
            if m:
                img_url = m.group(1).replace("\\/", "/")
        if not img_url:
            m = re.search(r'"image_original_url"\s*:\s*"([^"]+)"', html)
            if m:
                img_url = m.group(1).replace("\\/", "/")
        if not img_url:
            print("Pinterest: no image URL found in page (urllib fallback)")
            return None
        ext = img_url.rsplit(".", 1)[-1].split("?")[0][:4] or "jpg"
        if ext not in ("jpg", "jpeg", "png", "webp", "gif", "bmp"):
            ext = "jpg"
        filepath = os.path.join(DOWNLOAD_DIR, "pinterest_img." + ext)
        try:
            urllib.request.urlretrieve(img_url, filepath)
            if os.path.exists(filepath) and os.path.getsize(filepath) > 1024:
                return filepath
        except Exception:
            pass
        return None
    try:
        return await loop.run_in_executor(None, _dl)
    except Exception as e:
        print(f"download_pinterest_content urllib error: {e}")
        return None

async def download_image_content(url: str) -> str | None:
    info = await extract_info(url)
    if not info:
        return None
    img_url = info.get("thumbnail") or info.get("thumbnail_url") or ""
    if not img_url and info.get("formats"):
        for fmt in info["formats"]:
            if fmt.get("vcodec") in ("none", "") and fmt.get("url"):
                img_url = fmt.get("url", "")
                break
    if not img_url:
        return None
    ext = img_url.rsplit(".", 1)[-1].split("?")[0][:4] or "jpg"
    if ext not in ("jpg", "jpeg", "png", "webp", "gif", "bmp"):
        ext = "jpg"
    filepath = os.path.join(DOWNLOAD_DIR, f"image_{info.get('id', 'img')}.{ext}")
    try:
        import requests
        r = requests.get(img_url, timeout=30)
        r.raise_for_status()
        with open(filepath, "wb") as f:
            f.write(r.content)
        if os.path.getsize(filepath) > 1024:
            return filepath
    except Exception as e:
        print(f"download_image error: {e}")
    return None

def is_image_only(info: dict | None) -> bool:
    if not info:
        return False
    if info.get("extractor", "").startswith("Pinterest"):
        formats = info.get("formats", [])
        if not formats:
            return bool(info.get("thumbnail") or info.get("thumbnail_url"))
        has_video = any(f.get("vcodec") for f in formats)
        return not has_video
    return False

def check_file_size(filepath: str) -> bool:
    if not filepath or not os.path.exists(filepath):
        return False
    size_mb = os.path.getsize(filepath) / (1024 * 1024)
    return size_mb <= MAX_FILE_SIZE_MB

def cleanup(filepath: str):
    try:
        if filepath and os.path.exists(filepath):
            os.remove(filepath)
    except Exception:
        pass
