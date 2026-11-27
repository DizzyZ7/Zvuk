"""Playlist commands and one-click Telegram playback with ownership enforcement."""
from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from app.core.state import StateStore

from app.bot.handlers import dispatch_download
from app.core.config import Settings
from app.services.ad_manager import AdManager
from app.services.playlists import PlaylistService
from app.services.repository import Repository
from app.services.library import TrackLibrary
from app.services.search_sessions import SearchSessionError, read_search
from app.services.urls import InvalidMediaURL, parse_media_url
from app.services.user_service import UserService

router = Router(name="playlists")


def playlist_keyboard(items) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=("🎶 " + p.name)[:55], callback_data=f"plshow:{p.id}")]
        for p in items
    ])


def track_keyboard(items) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=("🎵 " + t.title)[:43], callback_data=f"plplay:{t.id}"),
            InlineKeyboardButton(text="✖", callback_data=f"pldrop:{t.id}"),
        ] for t in items
    ])


async def reply_playlists(message: Message, playlists: PlaylistService, user_id: int) -> None:
    rows = await playlists.list(user_id)
    if not rows:
        await message.answer(
            "🎼 Пока нет плейлистов. Создайте: /playlist new Моя музыка"
        )
        return
    await message.answer(
        f"🎼 Ваши плейлисты ({len(rows)}/25):",
        reply_markup=playlist_keyboard(rows),
    )


@router.message(Command("playlists"), F.chat.type == "private")
async def list_playlists(message: Message, playlists: PlaylistService) -> None:
    if message.from_user:
        await reply_playlists(message, playlists, message.from_user.id)


@router.message(Command("playlist"), F.chat.type == "private")
async def playlist_command(
    message: Message, playlists: PlaylistService, users: UserService,
) -> None:
    if not message.from_user:
        return
    await users.register(message.from_user)
    raw = (message.text or "").partition(" ")[2].strip()
    action, _, value = raw.partition(" ")
    if action == "new":
        try:
            entry = await playlists.create(message.from_user.id, value)
        except ValueError as exc:
            await message.answer(str(exc))
            return
        await message.answer(f"✅ Плейлист #{entry.id}: {entry.name}")
    elif action == "add":
        pid, sep, remainder = value.partition(" ")
        if not sep or not pid.isdecimal():
            await message.answer("Пример: /playlist add 1 https://youtu.be/... | Название")
            return
        url, _, label = remainder.strip().partition(" | ")
        try:
            media = parse_media_url(url)
            saved = await playlists.add(
                message.from_user.id, int(pid), media,
                title=label.strip() or f"Трек {media.platform}",
            )
        except (InvalidMediaURL, ValueError) as exc:
            await message.answer(str(exc))
            return
        await message.answer(
            "💾 Добавлено в плейлист." if saved else "Плейлист не найден."
        )
    elif action == "show" and value.isdecimal():
        pid = int(value)
        item = await playlists.get(message.from_user.id, pid)
        if item is None:
            await message.answer("Плейлист не найден.")
            return
        tracks = await playlists.tracks(message.from_user.id, pid)
        if not tracks:
            await message.answer(
                f"🎼 {item.name}: пока пусто. /playlist add {pid} ссылка | Название"
            )
            return
        await message.answer(
            f"🎼 {item.name}: первые {len(tracks)} треков.",
            reply_markup=track_keyboard(tracks),
        )
    elif action == "delete" and value.isdecimal():
        deleted = await playlists.delete(message.from_user.id, int(value))
        await message.answer(
            "Плейлист удален." if deleted else "Плейлист не найден."
        )
    else:
        await message.answer(
            "Плейлисты: /playlists\n"
            "/playlist new Название\n"
            "/playlist add ID https://ссылка | Название\n"
            "/playlist show ID\n"
            "/playlist delete ID"
        )


@router.callback_query(F.data.startswith("plshow:"))
async def show_playlist(
    callback: CallbackQuery, playlists: PlaylistService,
) -> None:
    if not callback.from_user or not isinstance(callback.message, Message):
        return
    pid = (callback.data or "").removeprefix("plshow:")
    if not pid.isdecimal():
        await callback.answer("Неверный идентификатор.", show_alert=True)
        return
    item = await playlists.get(callback.from_user.id, int(pid))
    if item is None:
        await callback.answer("Плейлист не найден.", show_alert=True)
        return
    tracks = await playlists.tracks(callback.from_user.id, int(pid))
    if tracks:
        await callback.message.answer(
            f"🎼 {item.name}: первые {len(tracks)} треков",
            reply_markup=track_keyboard(tracks),
        )
    else:
        await callback.message.answer(
            f"🎼 {item.name}: пока пусто. /playlist add {pid} ссылка | Название"
        )
    await callback.answer()


@router.callback_query(F.data.startswith("plplay:"))
async def play_playlist_track(
    callback: CallbackQuery, playlists: PlaylistService,
    bot: Bot, repo: Repository, redis: StateStore, ads: AdManager, settings: Settings,
) -> None:
    if not callback.from_user or not isinstance(callback.message, Message):
        return
    tid = (callback.data or "").removeprefix("plplay:")
    if not tid.isdecimal():
        await callback.answer("Неверный ID.", show_alert=True)
        return
    track = await playlists.track(callback.from_user.id, int(tid))
    if track is None:
        await callback.answer("Трек не найден.", show_alert=True)
        return
    await callback.answer()
    await dispatch_download(
        bot, callback.message.chat.id, callback.from_user.id,
        parse_media_url(track.url), "audio", repo, redis, ads, settings,
    )


@router.callback_query(F.data.startswith("pldrop:"))
async def remove_playlist_track(
    callback: CallbackQuery, playlists: PlaylistService,
) -> None:
    if not callback.from_user or not isinstance(callback.message, Message):
        return
    tid = (callback.data or "").removeprefix("pldrop:")
    if not tid.isdecimal():
        await callback.answer("Неверный ID.", show_alert=True)
        return
    track = await playlists.track(callback.from_user.id, int(tid))
    if track is None:
        await callback.answer("Трек уже удален.", show_alert=True)
        return
    await playlists.remove_track(callback.from_user.id, int(tid))
    updated = await playlists.tracks(callback.from_user.id, track.playlist_id)
    if updated:
        await callback.message.edit_reply_markup(reply_markup=track_keyboard(updated))
    else:
        await callback.message.edit_text("🎼 Плейлист теперь пуст.")
    await callback.answer("Удалено")



def destination_keyboard(playlists, *, origin: str, index: int) -> InlineKeyboardMarkup:
    """origin is a short server-generated search token or saved library id."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=("🎼 " + playlist.name)[:55],
            callback_data=f"plsave:{origin}:{index}:{playlist.id}",
        )] for playlist in playlists
    ])


@router.callback_query(F.data.startswith("pls:"))
async def choose_search_playlist(
    callback: CallbackQuery, redis: StateStore, playlists: PlaylistService,
) -> None:
    if not callback.from_user or not isinstance(callback.message, Message):
        return
    parts = (callback.data or "").split(":")
    if len(parts) != 3 or not parts[2].isdecimal():
        await callback.answer("Некорректный трек.", show_alert=True)
        return
    try:
        session = await read_search(redis, parts[1], callback.from_user.id)
        session.get(int(parts[2]))
    except SearchSessionError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    destinations = await playlists.list(callback.from_user.id)
    if not destinations:
        await callback.message.answer(
            "🎼 Сначала создайте плейлист командой /playlist new Моя музыка, "
            "затем снова нажмите ➕ под треком."
        )
        await callback.answer()
        return
    await callback.message.answer(
        "Выберите плейлист для добавления:",
        reply_markup=destination_keyboard(destinations, origin=parts[1], index=int(parts[2])),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("plsave:"))
async def save_search_to_playlist(
    callback: CallbackQuery, redis: StateStore, playlists: PlaylistService,
) -> None:
    if not callback.from_user or not isinstance(callback.message, Message):
        return
    parts = (callback.data or "").split(":")
    if len(parts) != 4 or not parts[2].isdecimal() or not parts[3].isdecimal():
        await callback.answer("Некорректные параметры.", show_alert=True)
        return
    try:
        session = await read_search(redis, parts[1], callback.from_user.id)
        track = session.get(int(parts[2]))
        saved = await playlists.add(
            callback.from_user.id, int(parts[3]), parse_media_url(track.url),
            title=track.title, artist=track.artist,
        )
    except (SearchSessionError, ValueError) as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    if not saved:
        await callback.answer("Этот плейлист недоступен.", show_alert=True)
        return
    await callback.answer("✅ Трек сохранен в плейлист!")


@router.callback_query(F.data.startswith("libpls:"))
async def choose_library_playlist(
    callback: CallbackQuery, library: TrackLibrary, playlists: PlaylistService,
) -> None:
    if not callback.from_user or not isinstance(callback.message, Message):
        return
    raw = (callback.data or "").removeprefix("libpls:")
    if not raw.isdecimal():
        await callback.answer("Некорректный трек.", show_alert=True)
        return
    track = await library.get(callback.from_user.id, int(raw))
    if track is None:
        await callback.answer("Трек не найден.", show_alert=True)
        return
    destinations = await playlists.list(callback.from_user.id)
    if not destinations:
        await callback.message.answer(
            "🎼 Создайте плейлист командой /playlist new Моя музыка."
        )
        await callback.answer()
        return
    await callback.message.answer(
        "Сохранить избранный трек в:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=("🎼 " + playlist.name)[:55],
                callback_data=f"libadd:{track.id}:{playlist.id}",
            )] for playlist in destinations
        ]),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("libadd:"))
async def save_library_to_playlist(
    callback: CallbackQuery, library: TrackLibrary, playlists: PlaylistService,
) -> None:
    if not callback.from_user:
        return
    parts = (callback.data or "").split(":")
    if len(parts) != 3 or not parts[1].isdecimal() or not parts[2].isdecimal():
        await callback.answer("Некорректные параметры.", show_alert=True)
        return
    track = await library.get(callback.from_user.id, int(parts[1]))
    if track is None:
        await callback.answer("Трек не найден.", show_alert=True)
        return
    try:
        saved = await playlists.add(
            callback.from_user.id, int(parts[2]),
            parse_media_url(track.url), title=track.title, artist=track.artist,
        )
    except ValueError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer(
        "✅ Сохранено в плейлист!" if saved else "Плейлист недоступен.",
        show_alert=not saved,
    )
