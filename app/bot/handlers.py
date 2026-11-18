import json
import logging
from uuid import uuid4

from aiogram import Bot, F, Router
from aiogram.filters import CommandStart
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message
from redis.asyncio import Redis

from app.bot.keyboards import format_keyboard, subscribe_keyboard
from app.bot.middlewares import subscription_missing
from app.core.config import Settings
from app.services.ad_manager import AdManager
from app.services.queue import enqueue_download
from app.services.repository import Repository
from app.services.urls import InvalidMediaURL, MediaURL, cache_key, find_media_url, parse_media_url
from app.services.user_service import UserService

log = logging.getLogger(__name__)
router = Router(name="users")

@router.message(CommandStart())
async def start(message: Message, users: UserService) -> None:
    if message.from_user:
        await users.register(message.from_user)
    await message.answer(
        "Привет! Отправь ссылку на YouTube, VK, Rutube, TikTok, "
        "Яндекс.Музыку или трек Spotify. Для видео можно выбрать аудио или видео. "
        "Скачивай только контент, на использование которого у тебя есть права."
    )

async def dispatch_download(
    bot: Bot, chat_id: int, user_id: int, media: MediaURL, kind: str,
    repo: Repository, redis: Redis, ads: AdManager,
) -> None:
    key = cache_key(media, kind)
    cached = await repo.cache_get(key)
    if cached:
        try:
            if kind == "audio":
                await bot.send_audio(chat_id, audio=cached, caption=await ads.caption())
            else:
                await bot.send_video(chat_id, video=cached, caption=await ads.caption())
            history_id = await repo.new_download(user_id, media.url, key, kind)
            await repo.update_download(history_id, "success", cache_hit=True)
            return
        except TelegramBadRequest as exc:
            if "wrong file" in str(exc).lower() or "invalid file" in str(exc).lower():
                await repo.cache_drop(key)
            else:
                raise
    job_id = await repo.new_download(user_id, media.url, key, kind)
    try:
        await enqueue_download(redis, job_id)
    except Exception:
        await repo.update_download(job_id, "failed", "Не удалось поставить задачу в очередь")
        raise
    await bot.send_message(chat_id, "⏳ Задача добавлена в очередь. Пришлю файл сюда.")

@router.message(F.chat.type == "private", F.text)
async def handle_link(
    message: Message, bot: Bot, redis: Redis, repo: Repository,
    users: UserService, ads: AdManager,
) -> None:
    if not message.from_user or not message.text:
        return
    if message.text.startswith("/"):
        return
    try:
        media = find_media_url(message.text)
    except InvalidMediaURL as exc:
        await message.answer(str(exc))
        return
    if media is None:
        await message.answer("Отправь ссылку на поддерживаемое видео или аудио.")
        return
    await users.register(message.from_user)
    if media.default_kind:
        await dispatch_download(bot, message.chat.id, message.from_user.id,
                                media, media.default_kind, repo, redis, ads)
        return
    token = uuid4().hex[:16]
    await redis.set(
        f"choice:{token}", json.dumps({"user": message.from_user.id, "url": media.url}),
        ex=3600,
    )
    await message.answer("В каком формате скачать?", reply_markup=format_keyboard(token))

@router.callback_query(F.data.startswith("fmt:"))
async def select_format(
    callback: CallbackQuery, bot: Bot, redis: Redis, repo: Repository,
    users: UserService, ads: AdManager,
) -> None:
    if not callback.from_user or not isinstance(callback.message, Message):
        await callback.answer("Сообщение недоступно.", show_alert=True)
        return
    parts = (callback.data or "").split(":")
    if len(parts) != 3 or parts[2] not in {"audio", "video"}:
        await callback.answer("Неизвестный формат.", show_alert=True)
        return
    data = await redis.get(f"choice:{parts[1]}")
    if data is None:
        await callback.answer("Выбор устарел, отправьте ссылку заново.", show_alert=True)
        return
    choice = json.loads(data)
    if choice["user"] != callback.from_user.id:
        await callback.answer("Эта кнопка предназначена другому пользователю.", show_alert=True)
        return
    media = parse_media_url(choice["url"])
    await users.register(callback.from_user)
    await callback.answer()
    await dispatch_download(bot, callback.message.chat.id, callback.from_user.id,
                            media, parts[2], repo, redis, ads)

@router.callback_query(F.data == "sub:check")
async def recheck_subscription(callback: CallbackQuery, bot: Bot, repo: Repository) -> None:
    if not isinstance(callback.message, Message):
        await callback.answer("Сообщение недоступно.", show_alert=True)
        return
    missing, available = await subscription_missing(bot, callback.from_user.id, repo)
    if not available:
        await callback.answer("Проверка недоступна. Сообщите администратору.", show_alert=True)
    elif missing:
        await callback.answer("Подписки еще не оформлены.", show_alert=True)
        await callback.message.answer("Осталось подписаться:",
                                      reply_markup=subscribe_keyboard(missing))
    else:
        await callback.answer("Подписка подтверждена!")
        await callback.message.answer("✅ Все подписки подтверждены. Отправьте ссылку еще раз.")
