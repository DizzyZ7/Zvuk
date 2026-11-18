"""Music discovery by text query; never treats search results as arbitrary URLs."""
import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from app.services.urls import parse_media_url

log = logging.getLogger(__name__)
VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


class MusicSearchError(Exception):
    pass


@dataclass(frozen=True)
class SearchResult:
    title: str
    artist: str
    url: str
    duration: int | None


def normalize_query(query: str) -> str:
    query = " ".join(query.split())
    if not 2 <= len(query) <= 120 or "://" in query:
        raise MusicSearchError("Введите название песни или исполнителя (2–120 символов).")
    return query


class MusicSearch:
    """Uses public YouTube search metadata; download is performed by the existing queue."""

    def __init__(self, concurrent_searches: int = 3):
        self._limit = asyncio.Semaphore(concurrent_searches)

    async def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        query = normalize_query(query)
        if not 1 <= limit <= 10:
            raise ValueError("Invalid search limit")
        async with self._limit:
            try:
                info = await asyncio.to_thread(self._search_sync, query, limit)
            except DownloadError as exc:
                log.warning("Music search failed: %s", str(exc)[:300])
                raise MusicSearchError("Поиск временно недоступен. Попробуйте позже.") from exc
            except Exception as exc:
                log.exception("Unexpected music search failure")
                raise MusicSearchError("Не получилось найти музыку. Попробуйте позже.") from exc
        return parse_search_entries(info, limit)

    @staticmethod
    def _search_sync(query: str, limit: int) -> dict[str, Any] | None:
        options: dict[str, Any] = {
            "extract_flat": "in_playlist",
            "skip_download": True,
            "noplaylist": True,
            "ignoreerrors": True,
            "quiet": True,
            "no_warnings": True,
            "socket_timeout": 15,
            "retries": 1,
            "js_runtimes": {"node": {}},
        }
        with YoutubeDL(options) as ydl:
            return ydl.extract_info(f"ytsearch{limit}:{query}", download=False)


def parse_search_entries(info: dict[str, Any] | None, limit: int = 5) -> list[SearchResult]:
    if not isinstance(info, dict):
        return []
    entries = info.get("entries")
    if not isinstance(entries, (list, tuple)):
        return []
    results: list[SearchResult] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        video_id = entry.get("id")
        title = entry.get("title")
        if not isinstance(video_id, str) or not VIDEO_ID.fullmatch(video_id):
            continue
        if video_id in seen or not isinstance(title, str) or not title.strip():
            continue
        duration = entry.get("duration")
        if duration is not None:
            if not isinstance(duration, (int, float)) or duration <= 0 or duration > 14400:
                continue
        url = f"https://www.youtube.com/watch?v={video_id}"
        parse_media_url(url)
        seen.add(video_id)
        results.append(SearchResult(
            title=title.strip()[:100],
            artist=str(entry.get("channel") or entry.get("uploader") or "")[:80],
            url=url,
            duration=int(duration) if duration is not None else None,
        ))
        if len(results) >= limit:
            break
    return results
