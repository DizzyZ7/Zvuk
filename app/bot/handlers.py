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
from app.services.queue import enqueue_download
from app.services.search_sessions import (
    PAGE_SIZE, SearchSessionError, create_search, read_search,
)
from app.bot.search_ui import render_search

from app.services.repository import Repository
from app.services.urls import (LINK_RE, InvalidMediaURL, MediaURL, cache_key,
                               find_media_url, parse_media_url, short_video_label)
from app.services.user_service import UserService

log = logging.getLogger(__name__)
router = Router(name="users")

@router.message(CommandStart())
async def start(message: Message, users: UserService) -> None:
    if message.from_user:
        await users.register(message.from_user)
    from app.bot.menu import home_keyboard

    await message.answer(
        "🎧 ZVUK  ·  Твоя музыка\n\n"
        "Ищи исполнителя или трек обычным сообщением. "
        "Одна подборка — сколько угодно разных песен из списка.\n\n"
        "🔎 Поиск   ·   🎼 Плейлисты   ·   ⭐ Избранное\n"
        "Отправь ссылку или аудиофрагмент для распознавания.\n\n"
        "Используй только материалы, на которые у тебя есть права.",
        reply_markup=home_keyboard(),
    )

async def dispatch_download(
    bot: Bot, chat_id: int, user_id: int, media: MediaURL, kind: str,
    repo: Repository, redis: Redis, ads: AdManager, settings: Settings,
    *, notify_rejection: bool = True,
) -> str:
    """Reserve a download in PostgreSQL before touching Redis or YouTube.

    A completed or in-progress file is always rejected for the same user and
    output format. First-time requests may reuse a global cached Telegram file.
    """
    owner_id = user_id if settings.ytdlp_cookies and user_id in settings.admin_ids else None
    key = cache_key(media, kind, owner_id=owner_id)
    if kind == "clip":
        status, job_id = await repo.reserve_clip_download(
            user_id, media.url, key,
            cache_key(media, "video", owner_id=owner_id),
            cache_key(media, "audio", owner_id=owner_id),
            settings.max_pending_per_user,
        )
    else:
        status, job_id = await repo.reserve_download(
            user_id, media.url, key, kind, settings.max_pending_per_user,
        )
    if status != "reserved":
        if notify_rejection:
            await bot.send_message(chat_id, download_status_message(status, settings))
        return status
    assert job_id is not None
    try:
        if kind != "clip":
            # Clip jobs have two output file IDs and are handled by the worker.
            cached = await repo.cache_get(key)
            if cached:
                placement = await ads.placement(user_id)
                try:
                    if kind in AUDIO_KINDS:
                        await bot.send_audio(
                            chat_id, audio=cached, caption=placement.caption,
                        )
                    else:
                        await bot.send_video(
                            chat_id, video=cached, caption=placement.caption,
                        )
                except TelegramBadRequest as exc:
                    if ("wrong file" in str(exc).lower()
                            or "invalid file" in str(exc).lower()):
                        await repo.cache_drop(key)
                    else:
                        raise
                else:
                    await repo.update_download(job_id, "success", cache_hit=True)
                    await ads.delivered(placement)
                    return "cached"
        await enqueue_download(redis, job_id)
    except Exception:
        # The reservation must never become an orphaned queued row.
        log.exception("Failed to dispatch reserved download %s", job_id)
        await repo.update_download(
            job_id, "failed", "Не удалось подготовить загрузку",
        )
        raise
    # User-facing acknowledgements must not invalidate an already queued job.
    await bot.send_message(
        chat_id,
        ("🎬 Ссылка принята. Пришлю видео и следом MP3 со звуком из него."
         if kind == "clip" else
         "⏳ В очереди. Отправлю файл, когда он будет готов."),
    )
    return "queued"

def download_status_message(status: str, settings: Settings) -> str:
    if status == "downloaded":
        return "✅ Ты уже получал этот файл. Повторная загрузка не требуется."
    if status == "pending":
        return "⏳ Этот файл уже скачивается или ожидает отправки."
    if status == "limit":
        return (
            f"🕓 Сейчас доступно не больше {settings.max_pending_per_user} "
            "ожидающих треков. Дождись одного из них и выбери следующий."
        )
    return "⚠️ Запрос не удалось принять. Попробуй еще раз."


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
        token = await create_search(redis, message.from_user.id, results,
                                    query=message.text)
        states = await _search_download_states(repo, results, message.from_user.id, settings)
        await progress.edit_text(
            render_search(results, message.text, page=0, states=states),
            reply_markup=search_keyboard(token, results, states=states),
        )
        return
    await users.register(message.from_user)
    matched_link = LINK_RE.search(message.text)
    short_label = (
        short_video_label(matched_link.group(0).rstrip(".,;!?)»"))
        if matched_link else None
    )
    if short_label in {"YouTube Shorts", "Instagram Reels", "TikTok"}:
        # These short-form links always deliver BOTH outputs, no format chooser.
        await dispatch_download(
            bot, message.chat.id, message.from_user.id,
            media, "clip", repo, redis, ads, settings,
        )
        return
    token = uuid4().hex[:16]
    await redis.set(
        f"choice:{token}", json.dumps({"user": message.from_user.id, "url": media.url}),
        ex=3600,
    )
    await message.answer(
        "🎚 Выбери формат — MP3, MP4 или другую скорость.\n"
        "Повторно уже полученный формат не отправляется:",
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
    # Keep the choice alive: users may select a different format without
    # resending the URL; PostgreSQL rejects duplicate delivery of each kind.
    await users.register(callback.from_user)
    result = await dispatch_download(
        bot, callback.message.chat.id, callback.from_user.id,
        media, parts[2], repo, redis, ads, settings, notify_rejection=False,
    )
    await callback.answer(
        download_status_message(result, settings)
        if result not in {"queued", "cached"} else
        ("✅ Отправлено из кэша." if result == "cached" else "⏳ Добавлено в очередь."),
        show_alert=result in {"downloaded", "limit"},
    )

def _keys_for_results(results, user_id: int, settings: Settings) -> list[str]:
    owner_id = user_id if settings.ytdlp_cookies and user_id in settings.admin_ids else None
    return [cache_key(parse_media_url(r.url), "audio", owner_id=owner_id)
            for r in results]


async def _search_download_states(
    repo: Repository, results, user_id: int, settings: Settings,
) -> dict[int, str]:
    keys = _keys_for_results(results, user_id, settings)
    statuses = await repo.download_states(user_id, keys)
    return {i: statuses[key] for i, key in enumerate(keys) if key in statuses}


async def _search_callback_context(
    callback: CallbackQuery, redis: Redis, token: str,
):
    if not callback.from_user or not isinstance(callback.message, Message):
        await callback.answer("Сообщение недоступно.", show_alert=True)
        return None
    try:
        return await read_search(redis, token, callback.from_user.id)
    except SearchSessionError as exc:
        await callback.answer(str(exc), show_alert=True)
        return None


async def _refresh_search(
    callback: CallbackQuery, token: str, session,
    repo: Repository, settings: Settings, *, page: int = 0,
) -> None:
    states = await _search_download_states(
        repo, session.results, callback.from_user.id, settings,
    )
    try:
        await callback.message.edit_text(
            render_search(session.results, session.query, page=page, states=states),
            reply_markup=search_keyboard(token, session.results, page=page, states=states),
        )
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            raise


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
        media = parse_media_url(session.get(index).url)
    except SearchSessionError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    # No Redis selection set or download lock: a single transactional PG
    # reservation rejects repeats, even across different search sessions.
    await users.register(callback.from_user)
    result = await dispatch_download(
        bot, callback.message.chat.id, callback.from_user.id,
        media, "audio", repo, redis, ads, settings, notify_rejection=False,
    )
    if result in {"downloaded", "pending", "limit"}:
        await callback.answer(
            download_status_message(result, settings),
            show_alert=result in {"downloaded", "limit"},
        )
    else:
        await callback.answer(
            "✅ Отправлено!" if result == "cached" else "⏳ Добавлено в очередь.",
        )
    await _refresh_search(
        callback, token, session, repo, settings, page=index // PAGE_SIZE,
    )


@router.callback_query(F.data.startswith("searchpage:"))
async def browse_search_page(
    callback: CallbackQuery, redis: Redis, repo: Repository, settings: Settings,
) -> None:
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
    await _refresh_search(callback, token, session, repo, settings, page=page)
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
