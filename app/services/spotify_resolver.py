import asyncio
import aiohttp
from app.core.config import Settings
from app.services.urls import MediaURL

class SpotifyResolutionError(Exception):
    pass

class SpotifyResolver:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._token: str | None = None
        self._valid_until = 0.0
        self._token_lock = asyncio.Lock()

    async def _access_token(self, http: aiohttp.ClientSession) -> str:
        if not self.settings.spotify_client_id or not self.settings.spotify_client_secret.get_secret_value():
            raise SpotifyResolutionError(
                "Для ссылок Spotify администратор должен настроить SPOTIFY_CLIENT_ID и SPOTIFY_CLIENT_SECRET."
            )
        async with self._token_lock:
            now = asyncio.get_running_loop().time()
            if self._token and now < self._valid_until:
                return self._token
            auth = aiohttp.BasicAuth(
                self.settings.spotify_client_id,
                self.settings.spotify_client_secret.get_secret_value(),
            )
            try:
                async with http.post(
                    "https://accounts.spotify.com/api/token",
                    data={"grant_type": "client_credentials"}, auth=auth,
                ) as response:
                    if response.status != 200:
                        raise SpotifyResolutionError("Spotify не выдал доступ к метаданным трека.")
                    data = await response.json()
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                raise SpotifyResolutionError("Spotify временно недоступен.") from exc
            self._token = str(data["access_token"])
            self._valid_until = now + max(1, int(data.get("expires_in", 3600)) - 60)
            return self._token

    async def search_query(self, media: MediaURL) -> str:
        track_id = media.url.rstrip("/").split("/")[-1]
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as http:
            token = await self._access_token(http)
            try:
                async with http.get(
                    f"https://api.spotify.com/v1/tracks/{track_id}",
                    headers={"Authorization": f"Bearer {token}"},
                ) as response:
                    if response.status != 200:
                        raise SpotifyResolutionError("Трек Spotify недоступен или не найден.")
                    data = await response.json()
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                raise SpotifyResolutionError("Не удалось получить метаданные Spotify.") from exc
        name = str(data.get("name", "")).strip()
        artists = ", ".join(str(a["name"]) for a in data.get("artists", []) if a.get("name"))
        if not name or not artists:
            raise SpotifyResolutionError("Не удалось определить название и исполнителя.")
        # Spotify supplies metadata only; search downloads an independently available source.
        return f"ytsearch1:{artists} - {name} official audio"
