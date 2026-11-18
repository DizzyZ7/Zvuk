"""Short-clip recognition with FFmpeg and documented AudD REST API."""
import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

import aiohttp

log = logging.getLogger(__name__)


class RecognitionError(Exception):
    pass


@dataclass(frozen=True)
class Recognition:
    title: str
    artist: str


class MusicRecognizer:
    ENDPOINT = "https://api.audd.io/"

    def __init__(self, api_token: str):
        self.api_token = api_token

    async def recognize(self, source: Path, folder: Path) -> Recognition | None:
        if not self.api_token:
            raise RecognitionError(
                "Распознавание пока не подключено: администратору нужен AUDD_API_TOKEN."
            )
        clip = folder / "recognition_clip.wav"
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source), "-t", "12", "-vn", "-ac", "1", "-ar", "16000",
            "-c:a", "pcm_s16le", str(clip),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=50)
        except TimeoutError as exc:
            proc.kill()
            await proc.communicate()
            raise RecognitionError("Не удалось обработать аудио за отведенное время.") from exc
        if proc.returncode != 0 or not clip.is_file() or not clip.stat().st_size:
            log.info("ffmpeg recognition failure: %s", stderr.decode(errors="replace")[-300:])
            raise RecognitionError("Не смог извлечь звук из файла.")
        if clip.stat().st_size > 2_000_000:
            raise RecognitionError("Аудиофрагмент слишком большой.")
        form = aiohttp.FormData()
        form.add_field("api_token", self.api_token)
        form.add_field(
            "file", clip.read_bytes(), filename="clip.wav", content_type="audio/wav",
        )
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    self.ENDPOINT, data=form, allow_redirects=False,
                ) as response:
                    if response.status != 200:
                        raise RecognitionError("Сервис распознавания временно недоступен.")
                    payload = await response.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
            raise RecognitionError("Сервис распознавания временно недоступен.") from exc
        if not isinstance(payload, dict) or payload.get("status") != "success":
            raise RecognitionError("Сервис распознавания отклонил запрос.")
        result = payload.get("result")
        if result is None:
            return None
        if not isinstance(result, dict):
            raise RecognitionError("Сервис вернул некорректный ответ.")
        title = result.get("title")
        artist = result.get("artist")
        if not isinstance(title, str) or not isinstance(artist, str):
            return None
        title, artist = title.strip()[:150], artist.strip()[:150]
        if not title or not artist:
            return None
        return Recognition(title=title, artist=artist)
