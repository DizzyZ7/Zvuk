"""Recognition of short voice/audio/video clips with cost and abuse controls."""
import asyncio
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.bot.keyboards import search_keyboard
from app.core.config import Settings
from app.services.music_search import MusicSearch, MusicSearchError
from app.services.premium import PremiumService
from app.services.queue import release_lock
from app.services.search_sessions import create_search
from app.services.recognition import MusicRecognizer, Recognition, RecognitionError
from app.services.user_service import UserService

log = logging.getLogger(__name__)
router = Router(name="recognition")
recognition_slots = asyncio.Semaphore(2)

# The two counters must be checked and incremented in one Lua script. This
# prevents races between instances and avoids paid API requests after the cap.
QUOTA_SCRIPT = """
local daily = tonumber(redis.call('GET', KEYS[1]) or '0')
local monthly = tonumber(redis.call('GET', KEYS[2]) or '0')
if daily >= tonumber(ARGV[1]) then return 1 end
if monthly >= tonumber(ARGV[2]) then return 2 end
if redis.call('INCR', KEYS[1]) == 1 then
  redis.call('EXPIRE', KEYS[1], 86400)
end
if redis.call('INCR', KEYS[2]) == 1 then
  redis.call('EXPIRE', KEYS[2], 3456000)
end
return 0
"""


async def reserve_recognition(
    redis: Redis, user_id: int, *, daily_limit: int, monthly_cap: int,
) -> int:
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    return int(await redis.eval(
        QUOTA_SCRIPT, 2,
        f"recognition:daily:{user_id}",
        f"recognition:month:{month}",
        daily_limit, monthly_cap,
    ))


async def recognize_file(
    bot: Bot, file_id: str, settings: Settings,
) -> Recognition | None:
    async with recognition_slots:
        with tempfile.TemporaryDirectory(prefix="zvuk_rec_", dir="/shared") as directory:
            folder = Path(directory)
            original = folder / "original_media"
            await bot.download(file_id, destination=original, timeout=90)
            if original.stat().st_size > settings.recognition_max_input_mb * 1_000_000:
                raise RecognitionError("Файл слишком большой. Пришлите короткий фрагмент.")
            return await MusicRecognizer(
                settings.audd_api_token.get_secret_value(),
            ).recognize(original, folder)


@router.message(
    F.chat.type == "private", F.voice | F.audio | F.video | F.video_note,
)
async def recognize_message(
    message: Message, bot: Bot, redis: Redis, settings: Settings,
    users: UserService, premium: PremiumService, music_search: MusicSearch,
) -> None:
    if not message.from_user:
        return
    if not settings.audd_api_token.get_secret_value():
        await message.answer("Распознавание музыки пока не подключено.")
        return
    media = message.voice or message.audio or message.video or message.video_note
    if media is None:
        return
    if (media.file_size or 0) > settings.recognition_max_input_mb * 1_000_000:
        await message.answer(
            f"Файл слишком большой. Лимит — {settings.recognition_max_input_mb} МБ. "
            "Пришлите короткий фрагмент."
        )
        return
    await users.register(message.from_user)
    user_id = message.from_user.id
    lock_key = f"recognition:busy:{user_id}"
    token = uuid4().hex
    try:
        acquired = await redis.set(lock_key, token, nx=True, ex=180)
    except RedisError:
        await message.answer("Распознавание временно недоступно. Попробуйте позже.")
        return
    if not acquired:
        await message.answer("⏳ Ваш предыдущий фрагмент еще обрабатывается.")
        return
    try:
        active = await premium.active_until(user_id)
        daily_limit = (
            settings.premium_recognitions_daily if active
            else settings.free_recognitions_daily
        )
        if user_id in settings.admin_ids:
            daily_limit = max(daily_limit, 1000)
        quota = await reserve_recognition(
            redis, user_id, daily_limit=daily_limit,
            monthly_cap=settings.recognition_monthly_cap,
        )
        if quota == 1:
            await message.answer(
                f"Лимит — {daily_limit} распознаваний за 24 часа. "
                "У Premium лимит выше: /premium."
            )
            return
        if quota == 2:
            await message.answer(
                "Лимит запросов к сервису распознавания исчерпан. "
                "Попробуйте позднее."
            )
            return

        status = await message.answer(
            "🎧 Анализирую фрагмент. Короткий звуковой отрывок "
            "будет передан AudD для распознавания."
        )
        try:
            result = await recognize_file(bot, media.file_id, settings)
        except (RecognitionError, TelegramAPIError, TimeoutError, OSError) as exc:
            log.warning("Recognition failed for user=%s: %s", user_id, exc)
            await status.edit_text(
                str(exc) if isinstance(exc, RecognitionError)
                else "Не удалось обработать файл. Попробуйте позже."
            )
            return
        if result is None:
            await status.edit_text(
                "Не удалось распознать песню. Попробуйте другой фрагмент."
            )
            return
        try:
            matches = await music_search.search(
                f"{result.artist} - {result.title}", limit=3,
            )
        except MusicSearchError:
            matches = []
        text = f"✅ Распознано: {result.artist} — {result.title}"
        if not matches:
            await status.edit_text(
                text + "\nПодходящей общедоступной записи пока не найдено."
            )
            return
        search_token = await create_search(redis, user_id, matches)
        await status.edit_text(
            text + "\nВот похожие записи из поиска:",
            reply_markup=search_keyboard(search_token, matches),
        )
    except RedisError:
        log.exception("Redis quota/lock service unavailable for recognition")
        await message.answer("Распознавание временно недоступно. Попробуйте позже.")
    finally:
        try:
            await release_lock(redis, lock_key, token)
        except RedisError:
            log.exception("Could not release recognition lock for user=%s", user_id)
