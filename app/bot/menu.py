"""Home menu and optional lyric-fragment discovery hints."""
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from redis.asyncio import Redis

from app.bot.keyboards import library_keyboard, search_keyboard
from app.bot.playlists import playlist_keyboard
from app.services.library import TrackLibrary
from app.services.music_search import MusicSearch, MusicSearchError
from app.services.playlists import PlaylistService
from app.services.search_sessions import create_search
from app.services.repository import Repository
from app.core.config import Settings
from app.bot.handlers import _search_download_states
from app.bot.search_ui import render_search

router = Router(name="menu")


def home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔎 Поиск", callback_data="home:search"),
         InlineKeyboardButton(text="🎙 Распознать", callback_data="home:recognize")],
        [InlineKeyboardButton(text="⭐ Избранное", callback_data="home:library"),
         InlineKeyboardButton(text="🎼 Плейлисты", callback_data="home:playlists")],
        [InlineKeyboardButton(text="🌟 Premium", callback_data="home:premium"),
         InlineKeyboardButton(text="❔ Помощь", callback_data="home:help")],
    ])


@router.message(Command("menu"), F.chat.type == "private")
async def show_menu(message: Message) -> None:
    await message.answer(
        "🎧 ZVUK  /  ГЛАВНАЯ\n\n"
        "Твоя музыка — в одном месте.\n"
        "Найди трек, сохрани в плейлист или отправь аудио для распознавания.\n\n"
        "↓ Выбери раздел",
        reply_markup=home_keyboard(),
    )


@router.message(Command("help"), F.chat.type == "private")
async def show_help(message: Message) -> None:
    await message.answer(
        "🎧 ZVUK  /  ПОМОЩЬ\n\n"
        "🔎 Напиши имя исполнителя — получишь список песен.\n"
        "🎧 Нажимай номера тех треков, которые нужны.\n"
        "✅ Уже полученные файлы повторно не отправляем.\n"
        "⏳ До пяти разных треков могут ждать в очереди.\n"
        "⭐ Добавляй в избранное, ➕ — в плейлист.\n\n"
        "Плейлисты: /playlists\n"
        "Поиск по фразе: /fragment слова песни\n"
        "О распознавании: /menu\n"
        "Условия: /terms и /privacy",
        reply_markup=home_keyboard(),
    )


@router.callback_query(F.data.startswith("home:"))
async def handle_menu(
    callback: CallbackQuery, library: TrackLibrary, playlists: PlaylistService,
) -> None:
    if not callback.from_user or not isinstance(callback.message, Message):
        return
    action = (callback.data or "").removeprefix("home:")
    if action == "search":
        await callback.message.answer(
            "Напиши название песни и исполнителя либо отправь ссылку.\n"
            "Поиск по фрагменту текста (экспериментально): /fragment слова песни."
        )
    elif action == "recognize":
        await callback.message.answer(
            "Пришли голосовое, аудио, видео или кружок. "
            "Распознавание доступно, если владелец подключил AudD."
        )
    elif action == "library":
        tracks = await library.list(callback.from_user.id, limit=20)
        if tracks:
            await callback.message.answer(
                "📚 Избранное:", reply_markup=library_keyboard(tracks),
            )
        else:
            await callback.message.answer("Пока пусто. /save ссылка")
    elif action == "playlists":
        rows = await playlists.list(callback.from_user.id)
        if rows:
            await callback.message.answer(
                "🎼 Ваши плейлисты:", reply_markup=playlist_keyboard(rows),
            )
        else:
            await callback.message.answer("Пока пусто. /playlist new Моя музыка")
    elif action == "premium":
        await callback.message.answer(
            "🌟 Premium отключает рекламные подписи и повышает лимит распознаваний. "
            "Подробности и статус: /premium"
        )
    elif action == "help":
        await callback.message.answer(
            "🔎 Поиск — отправь название песни\n"
            "🎧 Распознавание — пришли аудио или видео\n"
            "📚 /library — избранное\n🎼 /playlists — плейлисты\n"
            "🎼 /playlist — команды плейлистов\n"
            "🔍 /fragment слова — приблизительный поиск по фразе\n"
            "🔐 /privacy, /terms"
        )
    else:
        await callback.answer("Неизвестная кнопка.", show_alert=True)
        return
    await callback.answer()


@router.message(Command("fragment"), F.chat.type == "private")
async def fragment_search(
    message: Message, redis: Redis, music_search: MusicSearch,
    repo: Repository, settings: Settings,
) -> None:
    if not message.from_user:
        return
    query = (message.text or "").partition(" ")[2].strip()
    if len(query) < 5 or len(query) > 100:
        await message.answer(
            "Пример: /fragment часть текста песни (5–100 символов)"
        )
        return
    status = await message.answer(
        "🔍 Пробую найти песню по фразе. "
        "Это приблизительный YouTube-поиск, не поиск по полной базе текстов."
    )
    try:
        matches = await music_search.search(f"{query} lyrics", limit=5)
    except MusicSearchError as exc:
        await status.edit_text(str(exc))
        return
    if not matches:
        await status.edit_text("Совпадений не найдено. Попробуйте более длинную фразу.")
        return
    token = await create_search(redis, message.from_user.id, matches, query=f"Фраза: {query}")
    states = await _search_download_states(repo, matches, message.from_user.id, settings)
    await status.edit_text(
        render_search(matches, f"Фраза: {query}", states=states)
        + "\n\n⚠️ Поиск по фразе приблизительный.",
        reply_markup=search_keyboard(token, matches, states=states),
    )
