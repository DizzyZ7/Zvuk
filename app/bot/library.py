"""Per-user music bookmarks with safe ownership checks on every callback."""
import json

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from redis.asyncio import Redis

from app.bot.handlers import dispatch_download
from app.bot.keyboards import library_keyboard
from app.core.config import Settings
from app.services.ad_manager import AdManager
from app.services.library import TrackLibrary
from app.services.repository import Repository
from app.services.urls import InvalidMediaURL, parse_media_url
from app.services.user_service import UserService

router = Router(name="library")


@router.message(Command("save"), F.chat.type == "private")
async def save_command(
    message: Message, library: TrackLibrary, users: UserService,
) -> None:
    if not message.from_user:
        return
    await users.register(message.from_user)
    arg = (message.text or "").partition(" ")[2].strip()
    if not arg:
        await message.answer("Используйте /save https://ссылка-на-трек")
        return
    raw, _, label = arg.partition(" | ")
    try:
        media = parse_media_url(raw.strip())
    except InvalidMediaURL as exc:
        await message.answer(str(exc))
        return
    title = label.strip()[:255] or f"Трек из {media.platform}"
    await library.save(message.from_user.id, media, title=title)
    await message.answer("💾 Добавлено в вашу библиотеку. Откройте /library.")


@router.message(Command("library"), F.chat.type == "private")
async def show_library(message: Message, library: TrackLibrary) -> None:
    if not message.from_user:
        return
    tracks = await library.list(message.from_user.id, limit=20)
    if not tracks:
        await message.answer(
            "📚 Библиотека пуста. Используйте /save ссылка или 💾 в результатах поиска."
        )
        return
    count = await library.count(message.from_user.id)
    await message.answer(
        f"📚 Сохранено: {count}. Последние {len(tracks)} треков:",
        reply_markup=library_keyboard(tracks),
    )


@router.callback_query(F.data.startswith("stash:"))
async def save_search_result(
    callback: CallbackQuery, redis: Redis, library: TrackLibrary,
    users: UserService,
) -> None:
    if not callback.from_user:
        return
    parts = (callback.data or "").split(":")
    if len(parts) != 3 or not parts[2].isdigit():
        await callback.answer("Некорректная кнопка.", show_alert=True)
        return
    raw = await redis.get(f"search:{parts[1]}")
    if raw is None:
        await callback.answer("Поиск устарел. Отправьте запрос заново.", show_alert=True)
        return
    data = json.loads(raw)
    idx = int(parts[2])
    urls = data.get("urls", [])
    if data.get("user") != callback.from_user.id:
        await callback.answer("Это результаты другого пользователя.", show_alert=True)
        return
    if not 0 <= idx < len(urls):
        await callback.answer("Трек не найден.", show_alert=True)
        return
    media = parse_media_url(urls[idx])
    titles, artists = data.get("titles", []), data.get("artists", [])
    title = titles[idx] if idx < len(titles) else "Музыка"
    artist = artists[idx] if idx < len(artists) else ""
    await users.register(callback.from_user)
    await library.save(callback.from_user.id, media, title=title, artist=artist)
    await callback.answer("💾 Добавлено в библиотеку!")


@router.callback_query(F.data.startswith("libplay:"))
async def play_saved(
    callback: CallbackQuery, bot: Bot, repo: Repository, redis: Redis,
    ads: AdManager, settings: Settings, library: TrackLibrary,
) -> None:
    if not callback.from_user or not isinstance(callback.message, Message):
        return
    value = (callback.data or "").removeprefix("libplay:")
    if not value.isdigit():
        await callback.answer("Некорректный ID.", show_alert=True)
        return
    track = await library.get(callback.from_user.id, int(value))
    if track is None:
        await callback.answer("Трек удален или недоступен.", show_alert=True)
        return
    await callback.answer()
    await dispatch_download(
        bot, callback.message.chat.id, callback.from_user.id,
        parse_media_url(track.url), "audio", repo, redis, ads, settings,
    )


@router.callback_query(F.data.startswith("libdel:"))
async def delete_saved(
    callback: CallbackQuery, library: TrackLibrary,
) -> None:
    if not callback.from_user or not isinstance(callback.message, Message):
        return
    value = (callback.data or "").removeprefix("libdel:")
    if not value.isdigit():
        await callback.answer("Некорректный ID.", show_alert=True)
        return
    ok = await library.delete(callback.from_user.id, int(value))
    await callback.answer("Удалено" if ok else "Трек уже удален")
    tracks = await library.list(callback.from_user.id, limit=20)
    if tracks:
        await callback.message.edit_reply_markup(reply_markup=library_keyboard(tracks))
    else:
        await callback.message.edit_text("📚 Библиотека пуста.")
