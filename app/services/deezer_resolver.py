"""Resolve public Deezer track metadata, not DRM protected audio streams."""
import asyncio
import aiohttp

from app.services.urls import MediaURL


class DeezerResolutionError(Exception):
    pass


class DeezerResolver:
    async def search_query(self, media: MediaURL) -> str:
        track_id = media.url.rstrip("/").split("/")[-1]
        if not track_id.isdecimal():
            raise DeezerResolutionError("Некорректная ссылка Deezer.")
        timeout = aiohttp.ClientTimeout(total=15)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as http:
                async with http.get(
                    f"https://api.deezer.com/track/{track_id}",
                    allow_redirects=False,
                ) as response:
                    if response.status != 200:
                        raise DeezerResolutionError(
                            "Не удалось получить информацию о треке Deezer."
                        )
                    data = await response.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
            raise DeezerResolutionError("Deezer временно недоступен.") from exc
        if not isinstance(data, dict) or data.get("error"):
            raise DeezerResolutionError("Трек Deezer недоступен или не найден.")
        title = data.get("title")
        artist = data.get("artist")
        artist_name = artist.get("name") if isinstance(artist, dict) else None
        if not isinstance(title, str) or not isinstance(artist_name, str):
            raise DeezerResolutionError("У трека отсутствуют название или исполнитель.")
        title, artist_name = title.strip()[:120], artist_name.strip()[:120]
        if not title or not artist_name:
            raise DeezerResolutionError("У трека отсутствуют название или исполнитель.")
        return f"ytsearch1:{artist_name} - {title} official audio"
