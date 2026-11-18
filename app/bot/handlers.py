import json
import logging
from uuid import uuid4

from aiogram import Bot, F, Router
from aiogram.filters import CommandStart
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message
from redis.asyncio import Redis

from app.bot.keyboards import format_keyboard, search_keyboard, subscribe_keyboard
from app.bot.middlewares import subscription_missing
from app.core.config import Settings
from app.services.ad_manager import AdManager
from app.services.media_downloader import AUDIO_KINDS
from app.services.music_search import MusicSearch, MusicSearchError
from app.services.queue import enqueue_download, release_lock
from app.services.search_sessions import (
    MAX_BATCH_PER_TAP, PAGE_SIZE, SearchSessionError,
    create_search, lock_key, mark_selected, read_search, selected_indices,
)
from app.services.repository import Repository
from app.services.urls import InvalidMediaURL, MediaURL, cache_key, find_media_url, parse_media_url
from app.services.user_service import UserService

log = logging.getLogger(__name__)
router = Router(name="users")

@router.message(CommandStart())
async def start(message: Message, users: UserService) -> None:
    if message.from_user:
        await users.register(message.from_user)
    from app.bot.menu import home_keyboard

    await message.answer(
        "Привет! Отправь ссылку на YouTube, VK, Rutube, TikTok, "
        "Яндекс.Музыку, Spotify, Instagram или Pinterest. "
        "Можешь также написать название песни или исполнителя. "
        "Пришли голосовое, аудио, видео или кружок для распознавания музыки. "
        "Аудиофрагмент для распознавания отправляется сервису AudD. "
        "Скачивай только контент, на использование которого у тебя есть права.",
        reply_markup=home_keyboard(),
    )

async def dispatch_download(
    bot: Bot, chat_id: int, user_id: int, media: MediaURL, kind: str,
    repo: Repository, redis: Redis, ads: AdManager, settings: Settings,
) -> str:
    owner_id = user_id if settings.ytdlp_cookies and user_id in settings.admin_ids else None
    key = cache_key(media, kind, owner_id=owner_id)
    cached = await repo.cache_get(key)
    if cached:
        placement = await ads.placement(user_id)
        try:
            if kind in AUDIO_KINDS:
                await bot.send_audio(chat_id, audio=cached, caption=placement.caption)
            else:
                await bot.send_video(chat_id, video=cached, caption=placement.caption)
            await ads.delivered(placement)
            history_id = await repo.new_download(user_id, media.url, key, kind)
            await repo.update_download(history_id, "success", cache_hit=True)
            return "cached"
        except TelegramBadRequest as exc:
            if "wrong file" in str(exc).lower() or "invalid file" in str(exc).lower():
                await repo.cache_drop(key)
            else:
                raise
    # Cross-instance admission lock keeps concurrent callbacks from bypassing
    # the per-user pending limit. No row in the queue is made for a rejected item.
    token = uuid4().hex
    admission_key = f"queue-admission:{user_id}"
    acquired = await redis.set(admission_key, token, nx=True, ex=30)
    if not acquired:
        await bot.send_message(chat_id, "⏳ Другой запрос уже ставится в очередь. Повторите позже.")
        return "busy"
    try:
        if await repo.pending_downloads(user_id) >= settings.max_pending_per_user:
            await bot.send_message(
                chat_id, f"⏳ В очереди уже {settings.max_pending_per_user} задачи. "
                "Дождитесь завершения одной из них."
            )
            return "limit"
        job_id = await repo.new_download(user_id, media.url, key, kind)
        try:
            await enqueue_download(redis, job_id)
        except Exception:
            await repo.update_download(job_id, "failed", "Не удалось поставить задачу в очередь")
            raise
    finally:
        await release_lock(redis, admission_key, token)
    await bot.send_message(chat_id, "⏳ Задача добавлена в очередь. Пришлю файл сюда.")
    return "queued"

@router.message(F.chat.type == "private", F.text)
async def handle_link(
    message: Message, bot: Bot, redis: Redis, repo: Repository,
    users: UserService, ads: AdManager, settings: Settings,
    music_search: MusicSearch,
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
        await users.register(message.from_user)
        progress = await message.answer("🔎 Ищу музыку...")
        try:
            results = await music_search.search(message.text, limit=10)
        except MusicSearchError as exc:
            await progress.edit_text(str(exc))
            return
        if not results:
            await progress.edit_text(
                "Ничего не нашел. Попробуйте указать название песни и исполнителя."
            )
            return
        token = await create_search(redis, message.from_user.id, results)
        await progress.edit_text(
            f"🎵 Найдено {len(results)} записей. Можно скачать несколько треков, "
            "сохранить в плейлист или использовать кнопку пакетной загрузки. "
            "Результаты доступны 30 минут.",
            reply_markup=search_keyboard(token, results),
        )
        return
    await users.register(message.from_user)
    token = uuid4().hex[:16]
    await redis.set(
        f"choice:{token}", json.dumps({"user": message.from_user.id, "url": media.url}),
        ex=3600,
    )
    await message.answer(
        "Выберите формат или скорость:",
        reply_markup=format_keyboard(token, allow_video=media.default_kind is None),
    )

@router.callback_query(F.data.startswith("fmt:"))
async def select_format(
    callback: CallbackQuery, bot: Bot, redis: Redis, repo: Repository,
    users: UserService, ads: AdManager, settings: Settings,
) -> None:
    if not callback.from_user or not isinstance(callback.message, Message):
        await callback.answer("Сообщение недоступно.", show_alert=True)
        return
    parts = (callback.data or "").split(":")
    if len(parts) != 3 or parts[2] not in {"audio", "video", "fast", "slow"}:
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
    if media.default_kind and parts[2] == "video":
        await callback.answer("Для музыкальных ссылок доступно только аудио.", show_alert=True)
        return
    # Consume only a VALID choice, so an invalid format does not invalidate the buttons.
    consumed = await redis.getdel(f"choice:{parts[1]}")
    if consumed is None:
        await callback.answer("Формат уже выбран. Отправьте ссылку заново.", show_alert=True)
        return
    await users.register(callback.from_user)
    await callback.answer()
    await dispatch_download(bot, callback.message.chat.id, callback.from_user.id,
                            media, parts[2], repo, redis, ads, settings)

async def _search_callback_context(
    callback: CallbackQuery, redis: Redis, token: str,
):
    """Validate user ownership before permitting a fetch, batch or page change."""
    if not callback.from_user or not isinstance(callback.message, Message):
        await callback.answer("Сообщение недоступно.", show_alert=True)
        return None
    try:
        return await read_search(redis, token, callback.from_user.id)
    except SearchSessionError as exc:
        await callback.answer(str(exc), show_alert=True)
        return None


async def _refresh_search_keyboard(
    callback: CallbackQuery, redis: Redis, token: str, results,
    *, page: int = 0,
) -> None:
    selected = await selected_indices(redis, token)
    await callback.message.edit_reply_markup(
        reply_markup=search_keyboard(token, results, page=page, selected=selected),
    )


async def _submit_search_results(
    callback: CallbackQuery, token: str, indices: list[int],
    bot: Bot, redis: Redis, repo: Repository, ads: AdManager, settings: Settings,
    results,
) -> tuple[int, int]:
    lock = lock_key(token)
    owner = uuid4().hex
    acquired = await redis.set(lock, owner, ex=90, nx=True)
    if not acquired:
        await callback.answer("⏳ Предыдущий выбор еще обрабатывается.")
        return 0, 0
    accepted = 0
    exhausted = 0
    try:
        already = await selected_indices(redis, token)
        for index in indices:
            if index in already:
                continue
            media = parse_media_url(results[index].url)
            result = await dispatch_download(
                bot, callback.message.chat.id, callback.from_user.id,
                media, "audio", repo, redis, ads, settings,
            )
            if result in {"queued", "cached"}:
                await mark_selected(redis, token, index)
                accepted += 1
            elif result in {"limit", "busy"}:
                exhausted += 1
                break
        return accepted, exhausted
    finally:
        await release_lock(redis, lock, owner)


@router.callback_query(F.data.startswith("find:"))
async def select_search_result(
    callback: CallbackQuery, bot: Bot, redis: Redis, repo: Repository,
    users: UserService, ads: AdManager, settings: Settings,
) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 3 or not parts[2].isdigit():
        await callback.answer("Некорректная кнопка.", show_alert=True)
        return
    token, index = parts[1], int(parts[2])
    session = await _search_callback_context(callback, redis, token)
    if session is None:
        return
    try:
        session.get(index)
    except SearchSessionError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    if index in await selected_indices(redis, token):
        await callback.answer("Этот трек уже отправляли из этого поиска.")
        return
    await users.register(callback.from_user)
    accepted, blocked = await _submit_search_results(
        callback, token, [index], bot, redis, repo, ads, settings,
        session.results,
    )
    if accepted:
        await _refresh_search_keyboard(
            callback, redis, token, session.results, page=index // PAGE_SIZE,
        )
        await callback.answer("🎵 Трек отправляется!")
    elif not blocked:
        # The lock handler has already acknowledged the callback.
        return
    else:
        await callback.answer("Освободите место в очереди.", show_alert=True)


@router.callback_query(F.data.startswith("findall:"))
async def select_search_batch(
    callback: CallbackQuery, bot: Bot, redis: Redis, repo: Repository,
    users: UserService, ads: AdManager, settings: Settings,
) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 2:
        await callback.answer("Некорректная кнопка.", show_alert=True)
        return
    token = parts[1]
    session = await _search_callback_context(callback, redis, token)
    if session is None:
        return
    selected = await selected_indices(redis, token)
    remaining = [i for i in range(len(session.results)) if i not in selected]
    if not remaining:
        await callback.answer("Все треки из этого поиска уже отправлены.")
        return
    await users.register(callback.from_user)
    # Never queue more than three from a single button tap.
    accepted, blocked = await _submit_search_results(
        callback, token, remaining[:MAX_BATCH_PER_TAP],
        bot, redis, repo, ads, settings, session.results,
    )
    if accepted:
        await _refresh_search_keyboard(callback, redis, token, session.results)
        rest = len(remaining) - accepted
        await callback.answer(
            f"✅ Выбрано {accepted}. " +
            (f"Еще {rest}: нажмите кнопку позже." if rest else "Готово."),
        )
    elif blocked:
        await callback.answer("Очередь заполнена. Попробуйте после завершения загрузок.")
    # Otherwise already acknowledged by the lock handler.


@router.callback_query(F.data.startswith("searchpage:"))
async def browse_search_page(callback: CallbackQuery, redis: Redis) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 3 or not parts[2].isdigit():
        await callback.answer("Некорректная страница.", show_alert=True)
        return
    token, page = parts[1], int(parts[2])
    session = await _search_callback_context(callback, redis, token)
    if session is None:
        return
    max_page = (len(session.results) - 1) // PAGE_SIZE
    if page > max_page:
        await callback.answer("Такой страницы нет.", show_alert=True)
        return
    await _refresh_search_keyboard(callback, redis, token, session.results, page=page)
    await callback.answer()


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
