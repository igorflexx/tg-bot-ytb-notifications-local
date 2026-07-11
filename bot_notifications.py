from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import feedparser
import requests
from bs4 import BeautifulSoup
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_FILE = DATA_DIR / "channels.json"
TOKEN_FILE = BASE_DIR / "bot_token.txt"
HEADERS = {"User-Agent": "Mozilla/5.0"}
DEFAULT_LATEST_COUNT = 3
LATEST_COUNT_OPTIONS = (1, 3, 5, 10)


def load_token() -> str | None:
    if not TOKEN_FILE.exists():
        return None

    token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    if not token or "PASTE_YOUR_BOT_TOKEN_HERE" in token:
        return None
    return token


def home_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📺 Мои каналы", callback_data="BTN_MY_CHANNELS")],
            [InlineKeyboardButton("🆕 Последние видео", callback_data="BTN_LATEST")],
            [InlineKeyboardButton("⚙️ Настройки", callback_data="BTN_SETTINGS")],
        ]
    )


def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🏠 Домой", callback_data="BTN_HOME")]]
    )


def delete_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("❌ Удалить канал", callback_data="BTN_DELETE")]]
    )


def settings_kb(current_count: int) -> InlineKeyboardMarkup:
    rows = []
    row = []
    for count in LATEST_COUNT_OPTIONS:
        label = f"• {count}" if count == current_count else str(count)
        row.append(
            InlineKeyboardButton(
                label,
                callback_data=f"BTN_SET_LATEST_COUNT:{count}",
            )
        )
        if len(row) == 2:
            rows.append(row)
            row = []

    if row:
        rows.append(row)

    rows.append([InlineKeyboardButton("🏠 Домой", callback_data="BTN_HOME")])
    return InlineKeyboardMarkup(rows)


def watched_kb(channel_id: str, video_id: str, watched: bool) -> InlineKeyboardMarkup:
    if watched:
        label = "✅ Просмотрено"
        callback = "BTN_WATCHED_DONE"
    else:
        label = "👁 Отметить просмотренным"
        callback = f"BTN_MARK_WATCHED:{channel_id}:{video_id}"
    return InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=callback)]])


def normalize_bucket(bucket: dict | None) -> dict:
    base = bucket or {}
    channels = base.get("channels")
    if not isinstance(channels, list):
        channels = []

    last_videos = base.get("last_videos")
    if not isinstance(last_videos, dict):
        last_videos = {}

    settings = base.get("settings")
    if not isinstance(settings, dict):
        settings = {}

    latest_count = settings.get("latest_count", DEFAULT_LATEST_COUNT)
    if latest_count not in LATEST_COUNT_OPTIONS:
        latest_count = DEFAULT_LATEST_COUNT

    watched_videos = base.get("watched_videos")
    if not isinstance(watched_videos, dict):
        watched_videos = {}

    normalized_watched = {}
    for channel_id, video_ids in watched_videos.items():
        if isinstance(video_ids, list):
            normalized_watched[channel_id] = [str(video_id) for video_id in video_ids]

    normalized_last_videos = {}
    for channel_id, video_id in last_videos.items():
        normalized_video_id = extract_video_id(str(video_id))
        normalized_last_videos[channel_id] = normalized_video_id or str(video_id)

    return {
        "channels": channels,
        "last_videos": normalized_last_videos,
        "settings": {"latest_count": latest_count},
        "watched_videos": normalized_watched,
    }


def load_storage() -> dict:
    if not DATA_FILE.exists():
        return {}

    try:
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_storage(data: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_user_bucket(chat_id: int) -> dict:
    storage = load_storage()
    bucket = normalize_bucket(storage.get(str(chat_id)))
    storage[str(chat_id)] = bucket
    save_storage(storage)
    return bucket


def update_user_bucket(chat_id: int, bucket: dict) -> None:
    storage = load_storage()
    storage[str(chat_id)] = normalize_bucket(bucket)
    save_storage(storage)


def resolve_channel(url: str) -> str | None:
    if "youtube.com" not in url:
        return None
    if "/@" in url or "/channel/" in url:
        return url.rstrip("/")
    return None


def create_youtube_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)
    return session


def fetch_youtube_page(channel_url: str) -> str | None:
    try:
        session = create_youtube_session()
        response = session.get(channel_url, timeout=10)

        if "consent.youtube.com" in response.url:
            soup = BeautifulSoup(response.text, "html.parser")
            accept_form = None
            for form in soup.find_all("form"):
                data = {
                    field.get("name"): field.get("value", "")
                    for field in form.find_all("input")
                    if field.get("name")
                }
                if data.get("set_ytc") == "true":
                    accept_form = (form.get("action"), data)
                    break

            if not accept_form:
                return None

            action, data = accept_form
            response = session.post(action, data=data, timeout=10)

        if response.status_code != 200:
            return None

        return response.text
    except Exception:
        return None


def extract_channel_id(value: str) -> str | None:
    cleaned = value.rstrip("/")
    if cleaned.startswith("UC") and "/" not in cleaned:
        return cleaned
    if "/channel/" in cleaned:
        return cleaned.split("/channel/")[-1]
    return None


def get_channel_info(channel_url: str) -> dict | None:
    try:
        html = fetch_youtube_page(channel_url)
        if not html:
            return None

        soup = BeautifulSoup(html, "html.parser")
        og_title = soup.find("meta", property="og:title")
        og_url = soup.find("meta", property="og:url")
        if not og_title or not og_url:
            return None

        title = og_title["content"].replace(" - YouTube", "").strip()
        url = og_url["content"]
        channel_id = extract_channel_id(url)
        if not channel_id:
            return None

        return {"title": title, "url": url, "channel_id": channel_id}
    except Exception:
        return None


def extract_video_id(video_url: str) -> str | None:
    parsed = urlparse(video_url)
    query_video_id = parse_qs(parsed.query).get("v")
    if query_video_id:
        return query_video_id[0]

    if parsed.path:
        return parsed.path.rstrip("/").split("/")[-1]
    return None


def get_latest_videos(channel_ref: str, limit: int) -> list[dict]:
    try:
        channel_id = extract_channel_id(channel_ref)
        if not channel_id and "/@" in channel_ref:
            info = get_channel_info(channel_ref)
            if not info:
                return []
            channel_id = info["channel_id"]
        if not channel_id:
            return []

        rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
        feed = feedparser.parse(rss_url)
        if not feed.entries:
            return []

        videos = []
        for entry in feed.entries[:limit]:
            video_url = entry.link
            video_id = extract_video_id(video_url)
            if not video_id:
                continue

            try:
                published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc).isoformat()
            except Exception:
                published = datetime.now(timezone.utc).isoformat()

            videos.append(
                {
                    "id": video_id,
                    "title": entry.title,
                    "url": video_url,
                    "published": published,
                }
            )

        return videos
    except Exception:
        return []


def get_latest_video(channel_ref: str) -> dict | None:
    videos = get_latest_videos(channel_ref, limit=1)
    if not videos:
        return None
    return videos[0]


def format_video_time(iso_value: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_value)
    except Exception:
        dt = datetime.now(timezone.utc)
    dt_msk = dt.astimezone(timezone.utc) + timedelta(hours=3)
    return dt_msk.strftime("%d.%m.%Y %H:%M")


def is_video_watched(bucket: dict, channel_id: str, video_id: str) -> bool:
    watched_videos = bucket.get("watched_videos", {})
    return video_id in watched_videos.get(channel_id, [])


def mark_video_watched(bucket: dict, channel_id: str, video_id: str) -> None:
    watched_videos = bucket.setdefault("watched_videos", {})
    channel_watched = watched_videos.setdefault(channel_id, [])
    if video_id not in channel_watched:
        channel_watched.append(video_id)
        if len(channel_watched) > 200:
            del channel_watched[:-200]


def render_video_text(channel_title: str, video: dict, watched: bool) -> str:
    watched_text = "✅ Просмотрено" if watched else "🆕 Не просмотрено"
    return (
        f"📺 {channel_title}\n"
        f"🎬 {video['title']}\n"
        f"🕒 {format_video_time(video['published'])}\n"
        f"{watched_text}\n"
        f"{video['url']}"
    )


def replace_watched_status(text: str) -> str:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line in {"🆕 Не просмотрено", "✅ Просмотрено"}:
            lines[index] = "✅ Просмотрено"
            return "\n".join(lines)
    return text


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        chat_id = update.message.chat_id
    else:
        chat_id = update.callback_query.message.chat_id

    get_user_bucket(chat_id)
    await context.bot.send_message(
        chat_id=chat_id,
        text="Пришли ссылку на YouTube-канал, и я начну присылать уведомления.",
        reply_markup=home_kb(),
    )


async def show_channels(chat_id: int, context: ContextTypes.DEFAULT_TYPE, reply_to) -> None:
    bucket = get_user_bucket(chat_id)
    channels = bucket["channels"]
    if not channels:
        await reply_to.reply_text("📭 Каналов пока нет", reply_markup=back_kb())
        return

    text = "📺 Мои каналы:\n\n"
    for index, channel in enumerate(channels, start=1):
        text += f"{index}. {channel['title']}\n"

    await reply_to.reply_text(text.strip(), reply_markup=delete_kb())


async def show_latest(chat_id: int, context: ContextTypes.DEFAULT_TYPE, reply_to) -> None:
    bucket = get_user_bucket(chat_id)
    channels = bucket["channels"]
    if not channels:
        await reply_to.reply_text("📭 Сначала добавь канал", reply_markup=back_kb())
        return

    latest_count = bucket["settings"]["latest_count"]
    sent_any = False
    await reply_to.reply_text(
        f"🆕 Последние видео\nПоказываю по {latest_count} роликов на канал.",
        reply_markup=back_kb(),
    )

    for channel in channels:
        videos = get_latest_videos(channel["channel_id"], latest_count)
        if not videos:
            continue

        for video in videos:
            watched = is_video_watched(bucket, channel["channel_id"], video["id"])
            sent_any = True
            await reply_to.reply_text(
                render_video_text(channel["title"], video, watched),
                reply_markup=watched_kb(channel["channel_id"], video["id"], watched),
            )

    if not sent_any:
        await reply_to.reply_text("Не удалось получить последние видео.", reply_markup=back_kb())


async def handle_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.message.chat_id
    bucket = get_user_bucket(chat_id)
    channels = bucket["channels"]
    context.user_data["await_delete"] = False

    try:
        index = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Нужен номер канала из списка.", reply_markup=back_kb())
        return

    if index < 1 or index > len(channels):
        await update.message.reply_text("Такого номера канала нет.", reply_markup=back_kb())
        return

    removed = channels.pop(index - 1)
    bucket["last_videos"].pop(removed["channel_id"], None)
    update_user_bucket(chat_id, bucket)

    await update.message.reply_text(
        f"🗑 Канал удален: {removed['title']}",
        reply_markup=back_kb(),
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.user_data.get("await_delete"):
        await handle_delete(update, context)
        return

    chat_id = update.message.chat_id
    url = update.message.text.strip()
    channel_id = resolve_channel(url)
    if not channel_id:
        await update.message.reply_text("❌ Пришли ссылку вида youtube.com/@name или youtube.com/channel/ID")
        return

    info = get_channel_info(channel_id)
    if not info:
        await update.message.reply_text("❌ Канал не найден")
        return

    bucket = get_user_bucket(chat_id)
    channels = bucket["channels"]
    canonical_channel_id = info["channel_id"]
    if any(channel["channel_id"] == canonical_channel_id for channel in channels):
        await update.message.reply_text("⚠️ Этот канал уже добавлен", reply_markup=home_kb())
        return

    latest = get_latest_video(canonical_channel_id)
    if latest:
        bucket["last_videos"][canonical_channel_id] = latest["id"]

    channels.append(
        {
            "channel_id": canonical_channel_id,
            "title": info["title"],
            "url": info["url"],
        }
    )
    update_user_bucket(chat_id, bucket)

    await update.message.reply_text(
        f"✅ Канал добавлен: {info['title']}",
        reply_markup=home_kb(),
    )


async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id

    if query.data == "BTN_HOME":
        await start(update, context)
        return

    if query.data == "BTN_MY_CHANNELS":
        await show_channels(chat_id, context, query.message)
        return

    if query.data == "BTN_DELETE":
        context.user_data["await_delete"] = True
        await query.message.reply_text("Напиши номер канала, который нужно удалить.", reply_markup=back_kb())
        return

    if query.data == "BTN_LATEST":
        await show_latest(chat_id, context, query.message)
        return

    if query.data == "BTN_SETTINGS":
        bucket = get_user_bucket(chat_id)
        current_count = bucket["settings"]["latest_count"]
        await query.message.reply_text(
            f"⚙️ Настройки\nСколько последних роликов показывать по каждому каналу: {current_count}",
            reply_markup=settings_kb(current_count),
        )
        return

    if query.data.startswith("BTN_SET_LATEST_COUNT:"):
        count = int(query.data.split(":", 1)[1])
        bucket = get_user_bucket(chat_id)
        bucket["settings"]["latest_count"] = count
        update_user_bucket(chat_id, bucket)
        await query.message.reply_text(
            f"✅ Теперь показываю по {count} последних роликов на канал.",
            reply_markup=settings_kb(count),
        )
        return

    if query.data == "BTN_WATCHED_DONE":
        return

    if query.data.startswith("BTN_MARK_WATCHED:"):
        _, channel_id, video_id = query.data.split(":", 2)
        bucket = get_user_bucket(chat_id)
        mark_video_watched(bucket, channel_id, video_id)
        update_user_bucket(chat_id, bucket)

        if query.message and query.message.text:
            await query.edit_message_text(
                replace_watched_status(query.message.text),
                reply_markup=watched_kb(channel_id, video_id, True),
            )
        return


async def notify_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    storage = load_storage()
    for chat_id, bucket in storage.items():
        channels = bucket.get("channels", [])
        last_videos = bucket.get("last_videos", {})

        for channel in channels:
            video = get_latest_video(channel["channel_id"])
            if not video:
                continue

            if last_videos.get(channel["channel_id"]) == video["id"]:
                continue

            last_videos[channel["channel_id"]] = video["id"]
            await context.bot.send_message(
                chat_id=int(chat_id),
                text="🆕 Новое видео!\n\n" + render_video_text(channel["title"], video, False),
                reply_markup=watched_kb(channel["channel_id"], video["id"], False),
            )

        storage[chat_id] = bucket

    save_storage(storage)


def main() -> None:
    token = load_token()
    if not token:
        raise RuntimeError(
            f"Токен не найден. Открой файл {TOKEN_FILE} и вставь туда токен бота."
        )

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.job_queue.run_repeating(notify_job, interval=300, first=300)
    print("Bot Notifications запущен")
    app.run_polling()


if __name__ == "__main__":
    main()
