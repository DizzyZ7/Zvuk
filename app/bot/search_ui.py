"""Readable, compact Telegram discovery screens. Presentation only, no I/O."""
from collections.abc import Mapping, Sequence

from app.services.music_search import SearchResult
from app.services.search_sessions import PAGE_SIZE


def _duration(seconds: int | None) -> str:
    if not isinstance(seconds, int) or seconds <= 0:
        return ""
    minutes, secs = divmod(seconds, 60)
    return f"{minutes}:{secs:02d}"


def render_search(
    results: Sequence[SearchResult], query: str, *,
    page: int = 0, states: Mapping[int, str] | None = None,
) -> str:
    if not results:
        return "🎧 Zvuk\nНичего не найдено."
    page = max(0, min(page, (len(results) - 1) // PAGE_SIZE))
    states = states or {}
    total_pages = (len(results) + PAGE_SIZE - 1) // PAGE_SIZE
    label = " ".join(query.split())[:75] or "Музыкальная подборка"
    lines = [
        "🎧 ZVUK  /  ПОИСК",
        "",
        f"🔎 {label}",
        f"{len(results)} результатов   ·   {page + 1}/{total_pages}",
        "",
    ]
    for index in range(page * PAGE_SIZE, min((page + 1) * PAGE_SIZE, len(results))):
        song = results[index]
        status = states.get(index)
        mark = {"success": "✅", "queued": "⏳", "processing": "⏳"}.get(status, "🎵")
        title = " ".join(song.title.split())[:90]
        lines.append(f"{mark} {index + 1:02d}  {title}")
        artist = " ".join(song.artist.split())[:65]
        duration = _duration(song.duration)
        detail = "  ·  ".join(item for item in (artist, duration) if item)
        if detail:
            lines.append(f"     {detail}")
        lines.append("")
    lines.extend([
        "🎧 Получить   ⭐ Сохранить   ➕ Плейлист",
        "✅ Уже получено  ·  ⏳ В очереди",
        "Выбирай любые разные треки — без повторных загрузок.",
    ])
    return "\n".join(lines)
