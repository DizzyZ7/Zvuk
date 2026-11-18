"""Recognition of voice/audio/video messages and search of public matches."""
import json
import logging
import tempfile
from pathlib import Path
from uuid import uuid4

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message
from redis.asyncio import Redis

from app.bot.keyboards import search_keyboard
from app.core.config import Settings
from app.services.music_search import MusicSearch, MusicSearchError
from app.services.premium import PremiumService
from app.services.recognition import MusicRecognizer, RecognitionError
from app.services.user_service import UserService

log = logging.getLogger(__name__)
router = Router(name="recognition")


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
    if not media:
        return
    if (media.file_size or 0) > settings.recognition_max_input_mb * 1_000_000:
        await message.answer(
            f"Файл слишком большой. Лимит — {settings.recognition_max_input_mb} МБ. "
            "Пришлите короткий фрагмент."
        )
        return
    await users.register(message.from_user)
    active = await premium.active_until(message.from_user.id)
    daily_limit = (
        settings.premium_recognitions_daily if active
        else settings.free_recognitions_daily
    )
    # Increment/expire atomically so concurrent voice messages cannot bypass quotas.
    key = f"recognition:daily:{message.from_user.id}"
    usage = int(await redis.eval(
        "local n=redis.call('INCR',KEYS[1]);"
        "if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]);end;return n",
        1, key, 86400,
    ))
    if usage > daily_limit and message.from_user.id not in settings.admin_ids:
        await message.answer(
            f"Лимит распознаваний: {daily_limit} за 24 часа. "
            "Дополнительные запросы доступны с /premium."
        )
        return
    status = await message.answer("🎧 Анализирую фрагмент. Сервису AudD будет передан звук.")
    try:
        with tempfile.TemporaryDirectory(prefix="zvuk_rec_", dir="/shared") as directory:
            folder = Path(directory)
            original = folder / "original_media"
            await bot.download(media.file_id, destination=original, timeout=90)
            result = await MusicRecognizer(
                settings.audd_api_token.get_secret_value(),
            ).recognize(original, folder)
    except (RecognitionError, TelegramAPIError, TimeoutError) as exc:
        log.warning("Recognition failed for user=%s: %s", message.from_user.id, exc)
        await status.edit_text(
            str(exc) if isinstance(exc, RecognitionError) else
            "Не удалось получить файл или обработать аудио. Попробуйте позже."
        )
        return
    if result is None:
        await status.edit_text("Не удалось распознать песню. Попробуйте другой фрагмент.")
        return
    try:
        matches = await music_search.search(
            f"{result.artist} - {result.title}", limit=3,
        )
    except MusicSearchError:
        matches = []
    message_text = f"✅ Распознано: {result.artist} — {result.title}"
    if not matches:
        await status.edit_text(message_text + "\nПодходящей открытой записи пока не найдено.")
        return
    token = uuid4().hex[:16]
    await redis.set(
        f"search:{token}",
        json.dumps({
            "user": message.from_user.id,
            "urls": [item.url for item in matches],
            "titles": [item.title for item in matches],
            "artists": [item.artist for item in matches],
        }), ex=900,
    )
    await status.edit_text(
        message_text + "\nВот похожие записи из поиска:",
        reply_markup=search_keyboard(token, matches),
    )
