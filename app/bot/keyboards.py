from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from app.models import SponsorChannel
from app.services.music_search import SearchResult
from app.models import SavedTrack

def format_keyboard(token: str, *, allow_video: bool = True) -> InlineKeyboardMarkup:
    standard = [
        InlineKeyboardButton(text="🎵 MP3", callback_data=f"fmt:{token}:audio"),
    ]
    if allow_video:
        standard.append(
            InlineKeyboardButton(text="🎬 MP4", callback_data=f"fmt:{token}:video")
        )
    return InlineKeyboardMarkup(inline_keyboard=[
        standard,
        [
            InlineKeyboardButton(text="⚡ 1.25×", callback_data=f"fmt:{token}:fast"),
            InlineKeyboardButton(text="🌙 0.80×", callback_data=f"fmt:{token}:slow"),
        ],
    ])

def search_keyboard(token: str, results: list[SearchResult]) -> InlineKeyboardMarkup:
    rows = []
    for number, result in enumerate(results, start=1):
        label = f"{number}. {result.title}"
        if result.artist:
            label += f" — {result.artist}"
        rows.append([
            InlineKeyboardButton(
                text=("🎧 " + label)[:56], callback_data=f"find:{token}:{number - 1}",
            ),
            InlineKeyboardButton(
                text="💾", callback_data=f"stash:{token}:{number - 1}",
            ),
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def library_keyboard(tracks: list[SavedTrack]) -> InlineKeyboardMarkup:
    rows = []
    for track in tracks:
        rows.append([
            InlineKeyboardButton(
                text=("🎵 " + track.title)[:48], callback_data=f"libplay:{track.id}",
            ),
            InlineKeyboardButton(text="🗑", callback_data=f"libdel:{track.id}"),
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def subscribe_keyboard(channels: list[SponsorChannel]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"📢 {channel.title[:40]}", url=channel.join_url)]
            for channel in channels]
    rows.append([InlineKeyboardButton(text="✅ Проверить подписку", callback_data="sub:check")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def broadcast_confirmation() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Запустить рассылку", callback_data="adm:bc:send"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="adm:bc:cancel"),
    ]])


def broadcast_stop_keyboard(job_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🛑 Остановить рассылку", callback_data=f"adm:bcancel:{job_id}"),
    ]])


def admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="adm:stats")],
        [InlineKeyboardButton(text="🧪 Проверить систему", callback_data="adm:health")],
        [InlineKeyboardButton(text="📢 Спонсорские каналы", callback_data="adm:channels")],
        [InlineKeyboardButton(text="📝 Рекламная подпись", callback_data="adm:ads")],
        [InlineKeyboardButton(text="📈 Рекламные кампании", callback_data="adm:campaigns")],
        [InlineKeyboardButton(text="📨 Рассылка", callback_data="adm:broadcast")],
    ])
