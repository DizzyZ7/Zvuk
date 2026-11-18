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
    *, page: int = 0, states: dict[int, str] | None = None,
) -> InlineKeyboardMarkup:
    """One compact numbered action row per track; no batch download controls."""
    from app.services.search_sessions import PAGE_SIZE

    if not results:
        return InlineKeyboardMarkup(inline_keyboard=[])
    states = states or {}
    page = max(0, min(page, (len(results) - 1) // PAGE_SIZE))
    rows = []
    for index in range(page * PAGE_SIZE, min((page + 1) * PAGE_SIZE, len(results))):
        state = states.get(index)
        status_icon = (
            "✅" if state == "success" else
            "⏳" if state in {"queued", "processing"} else "🎧"
        )
        rows.append([
            InlineKeyboardButton(
                text=f"{status_icon}  {index + 1:02d}",
                callback_data=f"find:{token}:{index}",
            ),
            InlineKeyboardButton(
                text="⭐ В избранное", callback_data=f"stash:{token}:{index}",
            ),
            InlineKeyboardButton(
                text="➕ Плейлист", callback_data=f"pls:{token}:{index}",
            ),
        ])
    if len(results) > PAGE_SIZE:
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(
                text="‹ Назад", callback_data=f"searchpage:{token}:{page - 1}",
            ))
        nav.append(InlineKeyboardButton(
            text=f"{page + 1} / {(len(results) + PAGE_SIZE - 1) // PAGE_SIZE}",
            callback_data=f"searchpage:{token}:{page}",
        ))
        if (page + 1) * PAGE_SIZE < len(results):
            nav.append(InlineKeyboardButton(
                text="Далее ›", callback_data=f"searchpage:{token}:{page + 1}",
            ))
        rows.append(nav)
    if any(states.get(i) in {"queued", "processing"} for i in range(
        page * PAGE_SIZE, min((page + 1) * PAGE_SIZE, len(results))
    )):
        rows.append([InlineKeyboardButton(
            text="↻ Обновить статусы", callback_data=f"searchpage:{token}:{page}",
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
