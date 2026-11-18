import asyncio
import itertools
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError
from app.core.config import Settings
from app.services.deezer_resolver import DeezerResolver, DeezerResolutionError
from app.services.spotify_resolver import SpotifyResolver, SpotifyResolutionError
from app.services.urls import MediaURL

log = logging.getLogger(__name__)

class MediaDownloadError(Exception):
    pass

@dataclass(frozen=True)
class DownloadedMedia:
    path: Path
    title: str
    performer: str | None
    duration: int | None

class MediaDownloader:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.spotify = SpotifyResolver(settings)
        self.deezer = DeezerResolver()
        self._proxies = itertools.cycle(settings.proxy_list) if settings.proxy_list else None

    async def download(self, media: MediaURL, kind: str, folder: Path, *, use_auth_cookies: bool = False) -> DownloadedMedia:
        if kind not in ("audio", "video"):
            raise MediaDownloadError("Неизвестный формат.")
        if media.platform in ("spotify", "deezer", "yandex") and kind == "video":
            raise MediaDownloadError("Для музыкальных сервисов доступно только аудио.")
        target = media.url
        if media.platform == "spotify":
            try:
                target = await self.spotify.search_query(media)
            except SpotifyResolutionError as exc:
                raise MediaDownloadError(str(exc)) from exc
        if media.platform == "deezer":
            try:
                target = await self.deezer.search_query(media)
            except DeezerResolutionError as exc:
                raise MediaDownloadError(str(exc)) from exc
        proxy = next(self._proxies) if self._proxies is not None else None
        opts: dict[str, Any] = {
            "format": "bestaudio/best" if kind == "audio" else (
                "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best[ext=mp4]/best"
            ),
            "outtmpl": str(folder / "%(id)s.%(ext)s"),
            "noplaylist": True,
            "playlistend": 1,
            "js_runtimes": {"node": {}},
            "socket_timeout": 30,
            "retries": 2,
            "fragment_retries": 2,
            "quiet": True,
            "no_warnings": True,
            "restrictfilenames": True,
            "max_filesize": self.settings.max_file_mb * 1_000_000,
            "match_filter": self._duration_filter,
            "cachedir": False,
        }
        if proxy:
            opts["proxy"] = proxy
        if self.settings.ytdlp_cookies and use_auth_cookies:
            cookies = Path(self.settings.ytdlp_cookies)
            if not cookies.is_file():
                raise MediaDownloadError("Файл cookies не найден на сервере.")
            opts["cookiefile"] = str(cookies)
        if kind == "audio":
            opts["postprocessors"] = [{
                "key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"
            }]
        else:
            opts["merge_output_format"] = "mp4"
        operation = asyncio.create_task(asyncio.to_thread(self._run_ytdlp, target, opts))
        try:
            info = await asyncio.shield(operation)
        except asyncio.CancelledError:
            # Let the downloader finish before TemporaryDirectory is removed.
            try:
                await operation
            finally:
                raise
        except DownloadError as exc:
            log.warning("yt-dlp failure: %s", str(exc)[:800])
            raise MediaDownloadError(self._human_error(str(exc))) from exc
        except Exception as exc:
            log.exception("Unexpected yt-dlp error")
            raise MediaDownloadError("Ошибка обработки медиа. Попробуйте другую ссылку.") from exc
        candidates = sorted(
            (p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in
             ((".mp3",) if kind == "audio" else (".mp4", ".mkv", ".webm", ".mov"))),
            key=lambda p: p.stat().st_mtime, reverse=True,
        )
        if not candidates:
            raise MediaDownloadError("Не удалось создать медиафайл.")
        path = candidates[0]
        if kind == "video" and path.suffix.lower() != ".mp4":
            path = await self._to_mp4(path)
        if path.stat().st_size > self.settings.max_file_mb * 1_000_000:
            raise MediaDownloadError("Файл превышает лимит Telegram (2000 МБ).")
        if isinstance(info, dict) and "entries" in info:
            info = next((e for e in info["entries"] if e), {})
        info = info if isinstance(info, dict) else {}
        duration = info.get("duration")
        return DownloadedMedia(
            path=path,
            title=str(info.get("track") or info.get("title") or "Аудио")[:255],
            performer=(str(info.get("artist") or info.get("uploader"))[:255]
                       if info.get("artist") or info.get("uploader") else None),
            duration=int(duration) if isinstance(duration, (int, float)) and duration > 0 else None,
        )

    def _duration_filter(self, info: dict[str, Any], *, incomplete: bool = False) -> str | None:
        duration = info.get("duration")
        if duration and duration > self.settings.max_duration_sec:
            return "MAX_DURATION_EXCEEDED"
        if info.get("is_live"):
            return "LIVE_STREAM_UNSUPPORTED"
        return None

    @staticmethod
    def _run_ytdlp(target: str, options: dict[str, Any]) -> dict[str, Any] | None:
        with YoutubeDL(options) as ydl:
            return ydl.extract_info(target, download=True)

    @staticmethod
    def _human_error(message: str) -> str:
        lower = message.lower()
        if "max_duration_exceeded" in lower:
            return "Видео слишком длинное для установленного лимита."
        if "live_stream_unsupported" in lower:
            return "Прямые трансляции не поддерживаются."
        if "private" in lower or "login required" in lower or "sign in" in lower:
            return "Контент приватный или требует авторизации."
        if "geo" in lower or "country" in lower or "region" in lower:
            return "Контент недоступен в этом регионе."
        if "larger than" in lower or "max-filesize" in lower:
            return "Размер файла превышает лимит."
        if "unsupported url" in lower:
            return "Сервис или тип ссылки пока не поддерживается."
        return "Не удалось скачать файл: контент удален, недоступен или временно ограничен."

    @staticmethod
    async def _to_mp4(source: Path) -> Path:
        dest = source.with_suffix(".mp4")
        process = await asyncio.create_subprocess_exec(
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source), "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "24", "-c:a", "aac", "-movflags", "+faststart", str(dest),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, error = await asyncio.wait_for(process.communicate(), timeout=1200)
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.communicate()
            raise MediaDownloadError("Превышено время обработки видео.") from exc
        if process.returncode != 0 or not dest.is_file():
            log.warning("ffmpeg error: %s", error.decode(errors="replace")[-500:])
            raise MediaDownloadError("Ошибка конвертации видео.")
        source.unlink(missing_ok=True)
        return dest
