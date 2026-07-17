import os
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, InputFile, InputMediaPhoto
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

from config import BOT_TOKEN, OWNER_ID, BOT_USERNAME
from downloader import (
    detect_platform,
    download_media,
    download_audio_only,
    download_slideshow,
    download_image_content,
    download_tiktok_photos,
    download_pinterest_content,
    get_media_type,
    is_image_only,
    is_gif,
    check_file_size,
    cleanup,
    cleanup_temp_files,
    extract_info,
)
from languages import t, LANGUAGES, LANG_LIST
from data import get_or_create_user, increment_stat, is_premium, get_premium_until, get_daily_remaining, use_daily_download, DAILY_LIMIT, get_user, set_subscription, add_balance, _load, is_banned, ban_user, unban_user, SUBSCRIPTIONS, get_plan_name_ru

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

PLATFORM_ICONS = {"tiktok": "🎵", "youtube": "▶️", "instagram": "📸", "pinterest": "📌"}

def get_lang(context) -> str:
    return context.user_data.get("lang", "ru")

def lang_buttons():
    buttons = []
    row = []
    for i, code in enumerate(LANG_LIST):
        row.append(InlineKeyboardButton(LANGUAGES[code]["name"], callback_data=f"lang_{code}"))
        if len(row) == 2 or i == len(LANG_LIST) - 1:
            buttons.append(row)
            row = []
    return InlineKeyboardMarkup(buttons)

def main_menu_keyboard(lang: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("menu_download_video", lang), callback_data="menu_download")],
        [InlineKeyboardButton(t("menu_profile", lang), callback_data="menu_profile")],
        [InlineKeyboardButton(t("menu_language", lang), callback_data="menu_language")],
    ])

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int = None):
    lang = get_lang(context)
    cid = chat_id or update.effective_chat.id
    await context.bot.send_message(
        chat_id=cid,
        text=t("menu_title", lang),
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(lang),
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    get_or_create_user(user.id, user.first_name or "")

    if not context.user_data.get("lang"):
        await update.message.reply_text(
            LANGUAGES["ru"]["choose_language"],
            reply_markup=lang_buttons(),
        )
        return

    lang = get_lang(context)
    await update.message.reply_text(
        t("welcome", lang).format(name=user.first_name),
        parse_mode="HTML",
    )
    await show_main_menu(update, context)
    logger.info(f"Пользователь {user.id} ({user.first_name}) открыл меню, язык: {get_lang(context)}")

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(context)
    if not context.user_data.get("lang"):
        await update.message.reply_text(
            LANGUAGES["ru"]["choose_language"],
            reply_markup=lang_buttons(),
        )
        return
    await show_main_menu(update, context)

async def language_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        t("choose_language", get_lang(context)),
        reply_markup=lang_buttons(),
    )

async def send_media_file(chat_id: int, filepath: str, caption: str, context: ContextTypes.DEFAULT_TYPE) -> bool:
    fname = os.path.basename(filepath)
    mtype = get_media_type(filepath)

    try:
        with open(filepath, "rb") as f:
            if is_gif(filepath):
                await context.bot.send_animation(chat_id=chat_id, animation=InputFile(f, filename=fname), caption=caption)
            elif mtype == "video":
                await context.bot.send_video(chat_id=chat_id, video=InputFile(f, filename=fname), caption=caption, supports_streaming=True)
            elif mtype == "audio":
                await context.bot.send_audio(chat_id=chat_id, audio=InputFile(f, filename=fname), caption=caption)
            elif mtype == "photo":
                await context.bot.send_photo(chat_id=chat_id, photo=InputFile(f, filename=fname), caption=caption)
            else:
                await context.bot.send_document(chat_id=chat_id, document=InputFile(f, filename=fname), caption=caption)
        return True
    except Exception as e:
        logger.error(f"Ошибка отправки: {e}")
        return False

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(context)
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    if is_banned(user_id):
        await update.message.reply_text("🚫 Вы заблокированы в этом боте.")
        return

    url = update.message.text.strip()
    platform = detect_platform(url)
    if platform == "unknown":
        await show_main_menu(update, context)
        return

    status_msg = await update.message.reply_text(
        f"{PLATFORM_ICONS.get(platform, '🔗')} {t('recognizing', lang)}"
    )

    context.user_data["url"] = url
    context.user_data["platform"] = platform

    remaining = get_daily_remaining(user_id)
    if not is_premium(user_id) and remaining < 1:
        await status_msg.edit_text(t("daily_limit_reached", lang), parse_mode="HTML")
        return

    await status_msg.edit_text(f"📥 {t('downloading_video', lang)}")

    info = await extract_info(url)
    is_slideshow = info and info.get("_type") == "playlist" and bool(info.get("entries"))

    if not info and platform == "tiktok":
        images = await download_tiktok_photos(url)
        if images:
            media_group = [InputMediaPhoto(open(img, "rb")) for img in images]
            await context.bot.send_media_group(chat_id=chat_id, media=media_group)
            for img in images:
                cleanup(img)
            await status_msg.delete()
            if not is_premium(user_id):
                use_daily_download(user_id)
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"{t('video_ready', lang)}\n{t('success_footer', lang, bot_username=BOT_USERNAME)}",
            )
            return
        await status_msg.edit_text(f"❌ {t('error_occurred', lang)}")
        return

    if not info and platform == "pinterest":
        img_path = await download_pinterest_content(url)
        if img_path and check_file_size(img_path):
            caption = t("caption_video", lang, bot_username=BOT_USERNAME)
            ok = await send_media_file(chat_id, img_path, caption, context)
            cleanup(img_path)
            if ok:
                increment_stat(user_id, "video_downloads")
                if not is_premium(user_id):
                    use_daily_download(user_id)
                await status_msg.delete()
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"{t('video_ready', lang)}\n{t('success_footer', lang, bot_username=BOT_USERNAME)}",
                )
                return
        await status_msg.edit_text(f"❌ {t('error_occurred', lang)}")
        return

    if is_slideshow:
        images = await download_slideshow(url)
        if images:
            media_group = [InputMediaPhoto(open(img, "rb")) for img in images]
            await context.bot.send_media_group(chat_id=chat_id, media=media_group)
            for img in images:
                cleanup(img)
            await status_msg.delete()
            if not is_premium(user_id):
                use_daily_download(user_id)
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"{t('video_ready', lang)}\n{t('success_footer', lang, bot_username=BOT_USERNAME)}",
            )
            return

    is_image = is_image_only(info)
    if is_image:
        img_path = await download_image_content(url)
        if img_path and check_file_size(img_path):
            caption = t("caption_video", lang, bot_username=BOT_USERNAME)
            ok = await send_media_file(chat_id, img_path, caption, context)
            cleanup(img_path)
            if ok:
                increment_stat(user_id, "video_downloads")
                deducted = use_daily_download(user_id) if not is_premium(user_id) else None
                await status_msg.delete()
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"{t('video_ready', lang)}\n{t('success_footer', lang, bot_username=BOT_USERNAME)}",
                )
                return

    video_ok = False
    audio_ok = False

    filepath = await download_media(url)
    if filepath:
        if not check_file_size(filepath):
            cleanup(filepath)
            filepath = None
        else:
            await status_msg.edit_text(f"📤 {t('sending_video', lang)}")
            caption = t("caption_video", lang, bot_username=BOT_USERNAME)
            ok = await send_media_file(chat_id, filepath, caption, context)
            cleanup(filepath)
            if ok:
                video_ok = True
                increment_stat(user_id, "video_downloads")

    audio_filepath = await download_audio_only(url)
    if audio_filepath:
        if not check_file_size(audio_filepath):
            cleanup(audio_filepath)
            audio_filepath = None
        else:
            caption = t("caption_audio", lang, bot_username=BOT_USERNAME)
            ok = await send_media_file(chat_id, audio_filepath, caption, context)
            cleanup(audio_filepath)
            if ok:
                audio_ok = True
                increment_stat(user_id, "audio_downloads")

    if (video_ok or audio_ok) and not is_premium(user_id):
        use_daily_download(user_id)

    await status_msg.delete()

    if video_ok and audio_ok:
        result_text = f"{t('video_ready', lang)}\n{t('audio_ready', lang)}"
    elif video_ok:
        result_text = t('video_ready', lang)
    elif audio_ok:
        result_text = t('audio_ready', lang)
    else:
        result_text = f"❌ {t('error_occurred', lang)}"
        await context.bot.send_message(chat_id=chat_id, text=result_text)
        return

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"{result_text}\n{t('success_footer', lang, bot_username=BOT_USERNAME)}",
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    action = query.data
    lang = get_lang(context)

    if action == "show_languages":
        await query.edit_message_text(
            t("choose_language", lang),
            reply_markup=lang_buttons(),
        )
        return

    if action.startswith("lang_"):
        code = action.replace("lang_", "")
        context.user_data["lang"] = code
        lang = code
        await query.edit_message_text(t("language_changed", lang))
        await show_main_menu(update, context, update.effective_chat.id)
        return

    if action == "menu_download":
        buttons = [[InlineKeyboardButton(t("back_btn", lang), callback_data="menu_back")]]
        await query.edit_message_text(
            t("send_link_prompt", lang),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return

    if action == "menu_profile":
        await show_profile(update, context, query)
        return

    if action == "menu_language":
        await query.edit_message_text(
            t("choose_language", lang),
            reply_markup=lang_buttons(),
        )
        return

    if action == "menu_back":
        await query.edit_message_text(
            t("menu_title", lang),
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(lang),
        )
        return

    if action.startswith("sub_"):
        await handle_sub_callback(update, context, query, action)
        return

    if action.startswith("admin_"):
        await handle_admin_callback(update, context, query, action)
        return

    url = context.user_data.get("url")
    if not url:
        await query.edit_message_text(t("link_not_found", lang))
        return

    await query.edit_message_text(t("starting_download", lang))

    try:
        filepath = await download_media(url)
        if filepath and check_file_size(filepath):
            caption = t("caption_video", lang, bot_username=BOT_USERNAME)
            await send_media_file(update.effective_chat.id, filepath, caption, context)
            cleanup(filepath)
        else:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=t("error_occurred", lang))
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=t("error_occurred", lang),
        )

async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE, query):
    lang = get_lang(context)
    user = update.effective_user
    data = get_or_create_user(user.id, user.first_name or "")

    sub_status = t("profile_sub_premium", lang) if is_premium(user.id) else t("profile_sub_free", lang)
    sub_until = get_premium_until(user.id)
    sub_line = f"{sub_status}"
    if sub_until:
        sub_line += f" ({t('profile_sub_until', lang)}: {sub_until})"

    remaining = get_daily_remaining(user.id)
    daily_text = "" if is_premium(user.id) else f"\n📊 {t('daily_remaining', lang).format(n=remaining)}"

    text = (
        f"{t('profile_title', lang)}\n\n"
        f"{t('profile_user_id', lang)}: <code>{user.id}</code>\n"
        f"{t('profile_name', lang)}: {user.first_name}\n"
        f"{t('profile_registered', lang)}: {data.get('registered_at', '—')[:10]}\n\n"
        f"⭐ {t('profile_subscription', lang)}: {sub_line}\n"
        f"{t('profile_downloads', lang)}: {data['stats']['total_downloads']}\n"
        f"{t('profile_balance', lang)}: {data.get('balance', 0)} ₽{daily_text}\n"
    )

    buttons = [
        [InlineKeyboardButton("💎 Купить подписку", callback_data="sub_show")],
        [InlineKeyboardButton(t("back_btn", lang), callback_data="menu_back")],
    ]
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))

async def handle_sub_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, query, action: str):
    lang = get_lang(context)

    if action == "sub_show":
        text = "💎 <b>Доступные подписки</b>\n\n"
        for plan, info in SUBSCRIPTIONS.items():
            text += f"• <b>{info['name_ru']}</b> — {info['price']}₽\n"
        text += "\nВыберите подходящий план:"

        buttons = [
            [InlineKeyboardButton(f"{s['name_ru']} — {s['price']}₽", callback_data=f"sub_buy_{p}")]
            for p, s in SUBSCRIPTIONS.items()
        ]
        buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="menu_profile")])
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))

    elif action.startswith("sub_buy_"):
        plan = action.replace("sub_buy_", "")
        info = SUBSCRIPTIONS.get(plan)
        if not info:
            return

        context.user_data["pending_plan"] = plan
        text = (
            f"💎 <b>{info['name_ru']}</b> — {info['price']}₽\n\n"
            f"Нажмите «Отправить запрос» — администратор получит уведомление и активирует подписку."
        )
        buttons = [
            [InlineKeyboardButton("📩 Отправить запрос", callback_data=f"sub_paid_{plan}")],
            [InlineKeyboardButton("🔙 Назад", callback_data="sub_show")],
        ]
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))

    elif action.startswith("sub_paid_"):
        plan = action.replace("sub_paid_", "")
        info = SUBSCRIPTIONS.get(plan)
        user = update.effective_user

        await query.edit_message_text(
            f"✅ Запрос на <b>{info['name_ru']}</b> отправлен администратору!\n\n"
            f"Ожидайте подтверждения. Обычно это занимает до 5 минут.",
            parse_mode="HTML",
        )

        if OWNER_ID:
            await context.bot.send_message(
                chat_id=OWNER_ID,
                text=(
                    f"💰 <b>Запрос на оплату</b>\n\n"
                    f"👤 Пользователь: {user.first_name} (@{user.username or '—'})\n"
                    f"🆔 ID: <code>{user.id}</code>\n"
                    f"💎 План: {info['name_ru']} — {info['price']}₽\n\n"
                    f"Выдай подписку в админ-панели: /admin"
                ),
                parse_mode="HTML",
            )

ADMIN_IDS = [OWNER_ID] if OWNER_ID else []

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not OWNER_ID:
        await update.message.reply_text(
            f"⚠️ OWNER_ID не указан в .env\n\n"
            f"Твой Telegram ID: <code>{user_id}</code>\n"
            f"Добавь в файл .env строку:\n"
            f"<code>OWNER_ID={user_id}</code>\n\n"
            f"После этого перезапусти бота.",
            parse_mode="HTML",
        )
        return

    if not is_admin(user_id):
        await update.message.reply_text("🚫 Доступ запрещён.")
        return

    buttons = [
        [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton("👤 Найти пользователя", callback_data="admin_find")],
        [InlineKeyboardButton("⭐ Выдать подписку", callback_data="admin_gift")],
        [InlineKeyboardButton("💰 Начислить баланс", callback_data="admin_balance")],
        [InlineKeyboardButton("🚫 Забанить", callback_data="admin_ban")],
        [InlineKeyboardButton("✅ Разбанить", callback_data="admin_unban")],
        [InlineKeyboardButton("🔙 Назад", callback_data="menu_back")],
    ]
    await update.message.reply_text(
        "👑 <b>Админ-панель</b>\n\nВыберите действие:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons),
    )

async def handle_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, query, action: str):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await query.edit_message_text("🚫 Доступ запрещён.")
        return

    lang = get_lang(context)

    if action == "admin_stats":
        all_users = _load()
        total = len(all_users)
        premium = sum(1 for u in all_users.values() if u.get("subscription") == "premium")
        total_dl = sum(u["stats"]["total_downloads"] for u in all_users.values())
        await query.edit_message_text(
            f"📊 <b>Статистика</b>\n\n"
            f"👤 Всего пользователей: {total}\n"
            f"⭐ Premium: {premium}\n"
            f"📥 Всего скачиваний: {total_dl}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="admin_back")]]),
        )

    elif action == "admin_find":
        context.user_data["admin_action"] = "find_user"
        await query.edit_message_text(
            "👤 Введите Telegram ID пользователя:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Отмена", callback_data="admin_back")]]),
        )

    elif action == "admin_premium":
        context.user_data["admin_action"] = "premium_user"
        await query.edit_message_text(
            "⭐ Введите Telegram ID пользователя для выдачи Premium на 30 дней:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Отмена", callback_data="admin_back")]]),
        )

    elif action == "admin_balance":
        context.user_data["admin_action"] = "balance_user"
        await query.edit_message_text(
            "💰 Введите Telegram ID пользователя:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Отмена", callback_data="admin_back")]]),
        )

    elif action == "admin_gift":
        context.user_data["admin_action"] = "gift_user"
        await query.edit_message_text(
            "⭐ Введите Telegram ID пользователя, которому хотите выдать подписку:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Отмена", callback_data="admin_back")]]),
        )

    elif action == "admin_ban":
        context.user_data["admin_action"] = "ban_user"
        await query.edit_message_text(
            "🚫 Введите Telegram ID пользователя для блокировки (можно указать причину через пробел после ID):",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Отмена", callback_data="admin_back")]]),
        )

    elif action == "admin_unban":
        context.user_data["admin_action"] = "unban_user"
        await query.edit_message_text(
            "✅ Введите Telegram ID пользователя для разблокировки:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Отмена", callback_data="admin_back")]]),
        )

    elif action == "admin_back":
        buttons = [
            [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
            [InlineKeyboardButton("👤 Найти пользователя", callback_data="admin_find")],
            [InlineKeyboardButton("⭐ Выдать подписку", callback_data="admin_gift")],
            [InlineKeyboardButton("💰 Начислить баланс", callback_data="admin_balance")],
            [InlineKeyboardButton("🚫 Забанить", callback_data="admin_ban")],
            [InlineKeyboardButton("✅ Разбанить", callback_data="admin_unban")],
            [InlineKeyboardButton("🔙 Назад", callback_data="menu_back")],
        ]
        await query.edit_message_text(
            "👑 <b>Админ-панель</b>\n\nВыберите действие:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(buttons),
        )

async def handle_admin_text_inner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return False

    action = context.user_data.get("admin_action")
    if not action:
        return False

    text = update.message.text.strip()

    if action == "find_user":
        try:
            uid = int(text)
        except ValueError:
            await update.message.reply_text("❌ ID должен быть числом.")
            return True
        user_data = get_user(uid)
        if not user_data:
            await update.message.reply_text(f"❌ Пользователь {uid} не найден.")
        else:
            sub = "💎 Premium" if is_premium(uid) else "Бесплатная"
            until = get_premium_until(uid)
            until_text = f"\n📅 Действует до: {until}" if until else ""
            await update.message.reply_text(
                f"👤 <b>Пользователь {uid}</b>\n\n"
                f"Имя: {user_data.get('name', '—')}\n"
                f"⭐ Подписка: {sub}{until_text}\n"
                f"📥 Всего скачиваний: {user_data['stats']['total_downloads']}\n"
                f"💰 Баланс: {user_data.get('balance', 0)} ₽",
                parse_mode="HTML",
            )
        context.user_data.pop("admin_action", None)
        return True

    elif action == "premium_user":
        try:
            uid = int(text)
        except ValueError:
            await update.message.reply_text("❌ ID должен быть числом.")
            return True
        set_subscription(uid, "premium", 30)
        await update.message.reply_text(f"✅ Premium выдан пользователю {uid} на 30 дней!")
        context.user_data.pop("admin_action", None)
        return True

    elif action == "balance_user":
        try:
            context.user_data["admin_target"] = int(text)
        except ValueError:
            await update.message.reply_text("❌ ID должен быть числом.")
            return True
        context.user_data["admin_action"] = "balance_amount"
        await update.message.reply_text("💰 Введите сумму для начисления:")
        return True

    elif action == "balance_amount":
        try:
            amount = int(text)
        except ValueError:
            await update.message.reply_text("❌ Сумма должна быть числом.")
            return True
        target = context.user_data.get("admin_target")
        if target:
            add_balance(target, amount)
            await update.message.reply_text(f"✅ Пользователю {target} начислено {amount} ₽!")
        context.user_data.pop("admin_action", None)
        context.user_data.pop("admin_target", None)
        return True

    elif action == "gift_user":
        parts = text.split()
        try:
            uid = int(parts[0])
        except ValueError:
            await update.message.reply_text("❌ ID должен быть числом.")
            return True

        plan_keys = list(SUBSCRIPTIONS.keys())
        msg = "⭐ Введите план подписки (цифру):\n"
        for i, (k, v) in enumerate(SUBSCRIPTIONS.items(), 1):
            msg += f"{i}. {v['name_ru']} — {v['price']}₽\n"
        context.user_data["admin_gift_uid"] = uid
        context.user_data["admin_action"] = "gift_plan"
        await update.message.reply_text(msg)
        return True

    elif action == "gift_plan":
        try:
            idx = int(text) - 1
            plan = list(SUBSCRIPTIONS.keys())[idx]
        except (ValueError, IndexError):
            await update.message.reply_text("❌ Неверный номер. Попробуйте снова.")
            return True
        uid = context.user_data.get("admin_gift_uid")
        if uid:
            info = SUBSCRIPTIONS[plan]
            set_subscription(uid, plan, info["days"])
            await update.message.reply_text(f"✅ Подписка «{info['name_ru']}» выдана пользователю {uid}!")
            try:
                await context.bot.send_message(chat_id=uid, text=f"🎉 Вам выдана подписка «{info['name_ru']}»! Спасибо за доверие!")
            except Exception:
                pass
        context.user_data.pop("admin_action", None)
        context.user_data.pop("admin_gift_uid", None)
        return True

    elif action == "ban_user":
        parts = text.split(maxsplit=1)
        try:
            uid = int(parts[0])
        except ValueError:
            await update.message.reply_text("❌ ID должен быть числом.")
            return True
        reason = parts[1] if len(parts) > 1 else "Не указана"
        ban_user(uid, reason)
        await update.message.reply_text(f"🚫 Пользователь {uid} забанен.\nПричина: {reason}")
        context.user_data.pop("admin_action", None)
        return True

    elif action == "unban_user":
        try:
            uid = int(text.strip())
        except ValueError:
            await update.message.reply_text("❌ ID должен быть числом.")
            return True
        unban_user(uid)
        await update.message.reply_text(f"✅ Пользователь {uid} разбанен.")
        context.user_data.pop("admin_action", None)
        return True

    return False

async def handle_all_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info(f"💬 {user.id} ({user.first_name}): {update.message.text[:100]}")
    if await handle_admin_text_inner(update, context):
        return
    await handle_url(update, context)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Ошибка: {context.error}")

def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN не найден! Создай файл .env и укажи токен.")
        print("Ошибка: BOT_TOKEN не найден!")
        print("1. Создай файл .env в папке с ботом")
        print("2. Напиши в нём: BOT_TOKEN=твой_токен")
        print("3. Получить токен: https://t.me/BotFather")
        return

    app = Application.builder().token(BOT_TOKEN).build()

    async def post_init(application: Application):
        cleanup_temp_files()
        await application.bot.set_my_commands([
            BotCommand("start", "Запустить бота / Start"),
            BotCommand("menu", "Главное меню / Main menu"),
            BotCommand("language", "Сменить язык / Change language"),
            BotCommand("admin", "Админ-панель (только для владельца)"),
        ])
        if OWNER_ID:
            try:
                await application.bot.send_message(
                    chat_id=OWNER_ID,
                    text="🟢 <b>Бот запущен</b>\n\nБот работает и готов принимать запросы.",
                    parse_mode="HTML",
                )
            except Exception as e:
                logger.warning(f"Не удалось отправить уведомление о запуске: {e}")

    async def post_stop(application: Application):
        if OWNER_ID:
            try:
                await application.bot.send_message(
                    chat_id=OWNER_ID,
                    text="🔴 <b>Бот остановлен</b>",
                    parse_mode="HTML",
                )
            except Exception:
                pass

    app.post_init = post_init
    app.post_stop = post_stop

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(CommandHandler("language", language_command))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_all_text))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_error_handler(error_handler)

    logger.info("Бот запущен! Нажми Ctrl+C для остановки.")

    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
