"""Ownership-checked Redis sessions for multi-track music discovery."""
import json
import re
from dataclasses import dataclass
from uuid import uuid4

from app.core.state import StateStore

from app.services.music_search import SearchResult

SEARCH_TTL_SECONDS = 1800
PAGE_SIZE = 5
TOKEN_PATTERN = re.compile(r"^[0-9a-f]{16}$")


class SearchSessionError(ValueError):
    pass


@dataclass(frozen=True)
class SearchSession:
    user_id: int
    results: tuple[SearchResult, ...]
    query: str = ""

    def get(self, index: int) -> SearchResult:
        if not 0 <= index < len(self.results):
            raise SearchSessionError("Трек не найден.")
        return self.results[index]


def session_key(token: str) -> str:
    if not TOKEN_PATTERN.fullmatch(token):
        raise SearchSessionError("Некорректная кнопка поиска.")
    return f"search:{token}"


async def create_search(
    redis: StateStore, user_id: int, results: list[SearchResult], *,
    query: str = "",
) -> str:
    if not 1 <= len(results) <= 10:
        raise ValueError("Expected 1-10 search results")
    token = uuid4().hex[:16]
    payload = {
        "user": user_id,
        "query": " ".join(query.split())[:80],
        "urls": [r.url for r in results],
        "titles": [r.title for r in results],
        "artists": [r.artist for r in results],
        "durations": [r.duration for r in results],
    }
    await redis.set(
        session_key(token), json.dumps(payload, ensure_ascii=False),
        ex=SEARCH_TTL_SECONDS,
    )
    return token


async def read_search(redis: StateStore, token: str, user_id: int) -> SearchSession:
    raw = await redis.get(session_key(token))
    if raw is None:
        raise SearchSessionError(
            "Поиск устарел (30 минут). Отправьте имя исполнителя еще раз."
        )
    try:
        data = json.loads(raw)
        if data["user"] != user_id:
            raise SearchSessionError("Это результаты поиска другого пользователя.")
        urls = data["urls"]
        titles = data.get("titles", [])
        artists = data.get("artists", [])
        durations = data.get("durations", [])
        if not isinstance(urls, list) or not 1 <= len(urls) <= 10:
            raise ValueError("Invalid search result count")
        results = []
        for i, url in enumerate(urls):
            if not isinstance(url, str) or not url.startswith("https://www.youtube.com/watch?v="):
                raise ValueError("Invalid URL in search session")
            title = titles[i] if i < len(titles) and isinstance(titles[i], str) else "Музыка"
            artist = artists[i] if i < len(artists) and isinstance(artists[i], str) else ""
            duration = durations[i] if i < len(durations) else None
            results.append(SearchResult(
                title=title[:100], artist=artist[:80], url=url,
                duration=duration if isinstance(duration, int) else None,
            ))
        query = data.get("query", "")
        if not isinstance(query, str):
            query = ""
        return SearchSession(user_id=user_id, results=tuple(results), query=query[:80])
    except SearchSessionError:
        raise
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        raise SearchSessionError("Результаты поиска повреждены. Повторите запрос.") from exc

