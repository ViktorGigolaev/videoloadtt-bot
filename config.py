import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

OWNER_ID = os.getenv("OWNER_ID")
if OWNER_ID:
    OWNER_ID = int(OWNER_ID)

DOWNLOAD_DIR = "downloads"

MAX_FILE_SIZE_MB = 50

ALLOWED_USERS = []

COOKIES_FILE = "cookies.txt"

BOT_USERNAME = os.getenv("BOT_USERNAME", "videoloadtt_bot")
