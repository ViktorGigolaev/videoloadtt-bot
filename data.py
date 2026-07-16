import json
import os
import threading
from datetime import datetime, timedelta

DATA_FILE = "users_data.json"
_lock = threading.Lock()
DAILY_LIMIT = 5

SUBSCRIPTIONS = {
    "one_time": {"price": 5, "name_ru": "Разовая", "days": 0},
    "week":     {"price": 19, "name_ru": "Неделя", "days": 7},
    "month":    {"price": 29, "name_ru": "Месяц", "days": 30},
    "forever":  {"price": 49, "name_ru": "Навсегда", "days": 99999},
}

def _load():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def _save(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_or_create_user(user_id: int, name: str = "") -> dict:
    with _lock:
        data = _load()
        uid = str(user_id)
        if uid not in data:
            data[uid] = {
                "name": name,
                "registered_at": datetime.now().isoformat(),
                "subscription": "free",
                "subscription_until": None,
                "one_time_remaining": 0,
                "banned": False,
                "banned_reason": "",
                "balance": 0,
                "stats": {"total_downloads": 0, "video_downloads": 0, "audio_downloads": 0},
                "daily": {"date": "", "count": 0},
            }
            _save(data)
        elif data[uid].get("name") != name and name:
            data[uid]["name"] = name
            _save(data)
        return data[uid]

def get_user(user_id: int) -> dict | None:
    with _lock:
        data = _load()
        return data.get(str(user_id))

def update_user(user_id: int, updates: dict):
    with _lock:
        data = _load()
        uid = str(user_id)
        if uid in data:
            data[uid].update(updates)
            _save(data)

def increment_stat(user_id: int, stat_key: str):
    with _lock:
        data = _load()
        uid = str(user_id)
        if uid in data:
            data[uid]["stats"]["total_downloads"] += 1
            if stat_key in data[uid]["stats"]:
                data[uid]["stats"][stat_key] += 1
            _save(data)

def add_balance(user_id: int, amount: int):
    with _lock:
        data = _load()
        uid = str(user_id)
        if uid in data:
            data[uid]["balance"] += amount
            _save(data)

def is_banned(user_id: int) -> bool:
    user = get_user(user_id)
    return user.get("banned", False) if user else False

def ban_user(user_id: int, reason: str = ""):
    with _lock:
        data = _load()
        uid = str(user_id)
        if uid in data:
            data[uid]["banned"] = True
            data[uid]["banned_reason"] = reason
            _save(data)

def unban_user(user_id: int):
    with _lock:
        data = _load()
        uid = str(user_id)
        if uid in data:
            data[uid]["banned"] = False
            data[uid]["banned_reason"] = ""
            _save(data)

def set_subscription(user_id: int, plan: str, days: int = 30):
    with _lock:
        data = _load()
        uid = str(user_id)
        if uid in data:
            if plan == "forever":
                data[uid]["subscription"] = "forever"
                data[uid]["subscription_until"] = None
            elif plan == "one_time":
                data[uid]["subscription"] = "one_time"
                data[uid]["one_time_remaining"] = data[uid].get("one_time_remaining", 0) + 1
                data[uid]["subscription_until"] = None
            else:
                until = (datetime.now() + timedelta(days=days)).isoformat()
                data[uid]["subscription"] = plan
                data[uid]["subscription_until"] = until
            _save(data)

def is_premium(user_id: int) -> bool:
    user = get_user(user_id)
    if not user:
        return False
    if user.get("banned"):
        return False
    sub = user.get("subscription", "free")
    if sub == "forever":
        return True
    if sub == "one_time":
        return user.get("one_time_remaining", 0) > 0
    if sub in ("week", "month", "premium"):
        until = user.get("subscription_until")
        if until:
            return datetime.fromisoformat(until) > datetime.now()
    return False

def get_premium_until(user_id: int) -> str | None:
    user = get_user(user_id)
    if not user:
        return None
    sub = user.get("subscription", "free")
    if sub == "forever":
        return "навсегда"
    until = user.get("subscription_until")
    if until:
        dt = datetime.fromisoformat(until)
        if dt > datetime.now():
            return dt.strftime("%d.%m.%Y")
    return None

def get_plan_name_ru(plan: str) -> str:
    return SUBSCRIPTIONS.get(plan, {}).get("name_ru", plan)

def get_daily_remaining(user_id: int) -> int:
    with _lock:
        data = _load()
        uid = str(user_id)
        user = data.get(uid)
        if not user:
            return DAILY_LIMIT

        sub = user.get("subscription", "free")
        if sub in ("week", "month", "forever", "premium"):
            until = user.get("subscription_until")
            if sub == "forever" or (until and datetime.fromisoformat(until) > datetime.now()):
                return 9999

        if sub == "one_time":
            remaining = user.get("one_time_remaining", 0)
            if remaining > 0:
                return remaining

        daily = user.get("daily", {"date": "", "count": 0})
        today = datetime.now().strftime("%Y-%m-%d")
        if daily.get("date") != today:
            return DAILY_LIMIT
        return max(0, DAILY_LIMIT - daily.get("count", 0))

def use_daily_download(user_id: int) -> int:
    with _lock:
        data = _load()
        uid = str(user_id)
        if uid not in data:
            return 0
        user = data[uid]

        sub = user.get("subscription", "free")
        if sub in ("week", "month", "forever", "premium"):
            until = user.get("subscription_until")
            if sub == "forever" or (until and datetime.fromisoformat(until) > datetime.now()):
                return 9999

        if sub == "one_time":
            rem = user.get("one_time_remaining", 0)
            if rem > 0:
                user["one_time_remaining"] = rem - 1
                _save(data)
                return user["one_time_remaining"]

        daily = user.get("daily", {"date": "", "count": 0})
        today = datetime.now().strftime("%Y-%m-%d")
        if daily.get("date") != today:
            daily = {"date": today, "count": 0}
        daily["count"] += 1
        user["daily"] = daily
        _save(data)
        return max(0, DAILY_LIMIT - daily["count"])
