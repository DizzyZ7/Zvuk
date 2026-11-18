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

def search_keyboard(
    token: str, results: list[SearchResult] | tuple[SearchResult, ...],
    *, page: int = 0, selected: set[int] | None = None,
) -> InlineKeyboardMarkup:
    """Up to 10 results, five per page; all remain available for 30 minutes."""
    from app.services.search_sessions import PAGE_SIZE

    selected = selected or set()
    page = max(0, min(page, (len(results) - 1) // PAGE_SIZE))
    rows = []
    first = page * PAGE_SIZE
    for index, result in enumerate(results[first:first + PAGE_SIZE], start=first):
        label = f"{index + 1}. {result.title}"
        if result.artist:
            label += f" — {result.artist}"
        downloaded = index in selected
        rows.append([
            InlineKeyboardButton(
                text=("✅ " if downloaded else "🎧 ") + label[:38],
                callback_data=f"find:{token}:{index}",
            ),
            InlineKeyboardButton(text="💾", callback_data=f"stash:{token}:{index}"),
            InlineKeyboardButton(text="➕", callback_data=f"pls:{token}:{index}"),
        ])
    if len(results) > PAGE_SIZE:
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(
                text="⬅️ Назад", callback_data=f"searchpage:{token}:{page - 1}",
            ))
        nav.append(InlineKeyboardButton(
            text=f"{page + 1}/{(len(results) + PAGE_SIZE - 1) // PAGE_SIZE}",
            callback_data=f"searchpage:{token}:{page}",
        ))
        if first + PAGE_SIZE < len(results):
            nav.append(InlineKeyboardButton(
                text="Вперед ➡️", callback_data=f"searchpage:{token}:{page + 1}",
            ))
        rows.append(nav)
    remaining = max(0, len(results) - len(selected))
    if remaining:
        rows.append([InlineKeyboardButton(
            text=f"📥 Скачать следующие {min(remaining, 3)}",
            callback_data=f"findall:{token}",
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def library_keyboard(tracks: list[SavedTrack]) -> InlineKeyboardMarkup:
    rows = []
    for track in tracks:
        rows.append([
            InlineKeyboardButton(
                text=("🎵 " + track.title)[:48], callback_data=f"libplay:{track.id}",
            ),
            InlineKeyboardButton(text="➕", callback_data=f"libpls:{track.id}"),
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
        [InlineKeyboardButton(text="💰 Доходы и расходы", callback_data="adm:economics")],
        [InlineKeyboardButton(text="📨 Рассылка", callback_data="adm:broadcast")],
    ])
