import asyncio
import logging
import tempfile
from pathlib import Path
from uuid import uuid4

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest, TelegramEntityTooLarge, TelegramForbiddenError,
    TelegramNetworkError, TelegramRetryAfter, TelegramServerError,
)
from aiogram.types import FSInputFile
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError
from app.bot.keyboards import broadcast_stop_keyboard
from app.core.config import settings
from app.core.database import engine, session_factory
from app.core.redis import make_redis
from app.core.telegram import make_bot
from app.services.ad_manager import AdManager
from app.services.media_downloader import MediaDownloadError, MediaDownloader
from app.services.queue import (
    BROADCAST_STREAM, DOWNLOAD_STREAM, GROUP, STALE_AFTER_MS, acknowledge,
    ensure_groups, keep_pending_alive, release_lock,
)
from app.services.repository import Repository
from app.services.urls import parse_media_url

log = logging.getLogger(__name__)
MAX_TRANSIENT_RETRIES = 3

class Worker:
    def __init__(self, bot: Bot, redis: Redis, repo: Repository):
        self.bot = bot
        self.redis = redis
        self.repo = repo
        self.ads = AdManager(repo)
        self.downloader = MediaDownloader(settings)
        self.consumer = uuid4().hex[:12]

    async def send_cached(self, chat_id: int, kind: str, file_id: str) -> None:
        caption = await self.ads.caption()
        if kind == "audio":
            await self.bot.send_audio(chat_id, audio=file_id, caption=caption)
        else:
            await self.bot.send_video(chat_id, video=file_id, caption=caption)

    async def send_media(self, chat_id: int, kind: str, media) -> str:
        caption = await self.ads.caption()
        file = FSInputFile(media.path)
        if kind == "audio":
            sent = await self.bot.send_audio(
                chat_id, audio=file, caption=caption,
                title=media.title[:64],
                performer=media.performer[:64] if media.performer else None,
                duration=media.duration,
            )
            if not sent.audio:
                raise MediaDownloadError("Telegram не вернул ID аудиофайла.")
            return sent.audio.file_id
        sent = await self.bot.send_video(
            chat_id, video=file, caption=caption, supports_streaming=True,
            duration=media.duration,
        )
        if not sent.video:
            raise MediaDownloadError("Telegram не вернул ID видеофайла.")
        return sent.video.file_id

    async def notify_failure(self, user_id: int, error: str) -> None:
        try:
            await self.bot.send_message(user_id, f"❌ {error[:800]}")
        except Exception:
            log.warning("Cannot notify user %s about failed job", user_id)

    async def process_download(self, job_id: str) -> None:
        job = await self.repo.download(job_id)
        if job is None or job.status in {"success", "failed"}:
            return
        await self.repo.update_download(job_id, "processing")
        key, kind = job.cache_key, job.kind
        hit = False
        try:
            file_id = await self.repo.cache_get(key)
            if file_id:
                try:
                    await self.send_cached(job.user_id, kind, file_id)
                    hit = True
                    await self.repo.update_download(job_id, "success", cache_hit=True)
                    return
                except TelegramBadRequest as exc:
                    if "wrong file" in str(exc).lower() or "invalid file" in str(exc).lower():
                        await self.repo.cache_drop(key)
                    else:
                        raise
            lock_key = f"media-lock:{key}"
            token = uuid4().hex
            # Guard upload and download; a follower can reuse the resulting file_id.
            ttl = max(7200, settings.max_duration_sec * 3)
            obtained = await self.redis.set(lock_key, token, ex=ttl, nx=True)
            if not obtained:
                await self._await_other_download(job.user_id, kind, key, lock_key)
                await self.repo.update_download(job_id, "success", cache_hit=True)
                return
            try:
                file_id = await self.repo.cache_get(key)
                if file_id:
                    await self.send_cached(job.user_id, kind, file_id)
                    hit = True
                else:
                    with tempfile.TemporaryDirectory(prefix="zvuk_", dir="/shared") as folder:
                        # The Local Bot API runs in another container and must be
                        # able to traverse this temporary directory.
                        Path(folder).chmod(0o755)
                        media = await self.downloader.download(
                            parse_media_url(job.url), kind, Path(folder),
                            use_auth_cookies=bool(settings.ytdlp_cookies and
                                                  job.user_id in settings.admin_ids),
                        )
                        media.path.chmod(0o644)
                        file_id = await self.send_media(job.user_id, kind, media)
                        await self.repo.cache_put(key, file_id, kind)
                await self.repo.update_download(job_id, "success", cache_hit=hit)
            finally:
                await release_lock(self.redis, lock_key, token)
        except TelegramEntityTooLarge:
            error = "Telegram отклонил файл: превышен допустимый размер."
            await self.repo.update_download(job_id, "failed", error=error)
            await self.notify_failure(job.user_id, error)
        except (
            RedisError, SQLAlchemyError, TelegramNetworkError,
            TelegramServerError, TelegramRetryAfter,
        ) as exc:
            # Leave the message in the Redis pending list for XAUTOCLAIM.
            # Do not permanently fail a user job due to short infrastructure outages.
            attempt = await self.repo.record_download_retry(job_id)
            if attempt <= MAX_TRANSIENT_RETRIES:
                log.warning(
                    "Transient download error job=%s attempt=%s/%s type=%s",
                    job_id, attempt, MAX_TRANSIENT_RETRIES, type(exc).__name__,
                )
                raise
            error = "Сервис временно недоступен после нескольких попыток. Повторите запрос позже."
            await self.repo.update_download(job_id, "failed", error=error)
            await self.notify_failure(job.user_id, error)
        except Exception as exc:
            log.exception("Download failed job=%s", job_id)
            error = str(exc) if isinstance(exc, MediaDownloadError) else (
                "Не удалось отправить файл. Попробуйте позже."
            )
            await self.repo.update_download(job_id, "failed", error=error)
            await self.notify_failure(job.user_id, error)

    async def _await_other_download(
        self, chat_id: int, kind: str, key: str, lock_key: str,
    ) -> None:
        deadline = asyncio.get_running_loop().time() + max(7200, settings.max_duration_sec * 3)
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(3)
            cached = await self.repo.cache_get(key)
            if cached:
                try:
                    await self.send_cached(chat_id, kind, cached)
                    return
                except TelegramBadRequest as exc:
                    if "wrong file" in str(exc).lower() or "invalid file" in str(exc).lower():
                        await self.repo.cache_drop(key)
                    else:
                        raise
            if not await self.redis.exists(lock_key):
                raise MediaDownloadError("Параллельное скачивание завершилось без файла. Повторите запрос.")
        raise MediaDownloadError("Превышено время ожидания другого скачивания.")

    @staticmethod
    def progress_text(processed: int, total: int, failed: int, done: bool) -> str:
        ratio = 1.0 if done or not total else min(1.0, processed / total)
        filled = min(10, int(ratio * 10))
        return (
            ("✅ Рассылка завершена" if done else "📨 Рассылка") +
            f"\n[{'█' * filled}{'░' * (10-filled)}] {ratio:.0%}"
            f"\nОбработано: {processed}/{total}\nОшибок: {failed}"
        )

    async def process_broadcast(self, job_id: str) -> None:
        job = await self.repo.get_broadcast(job_id)
        if job is None or job.status in {"complete", "cancelled", "failed"}:
            return
        processed, failed, after = job.processed, job.failed, job.last_user_id
        while True:
            recipients = await self.repo.users_after(after, created_before=job.created_at)
            if not recipients:
                break
            for user_id in recipients:
                # Stop promptly when an administrator presses "Stop".
                if processed % 5 == 0:
                    current = await self.repo.get_broadcast(job_id)
                    if current is None or current.status == "cancelled":
                        return
                try:
                    await self.bot.copy_message(
                        chat_id=user_id, from_chat_id=job.source_chat_id,
                        message_id=job.source_message_id,
                    )
                except TelegramRetryAfter as exc:
                    await asyncio.sleep(exc.retry_after + 1)
                    try:
                        await self.bot.copy_message(
                            chat_id=user_id, from_chat_id=job.source_chat_id,
                            message_id=job.source_message_id,
                        )
                    except TelegramForbiddenError:
                        failed += 1
                        await self.repo.user_block(user_id)
                    except TelegramBadRequest:
                        failed += 1
                    except TelegramRetryAfter:
                        # Telegram is still throttling. Keep this item pending for recovery.
                        raise
                except TelegramForbiddenError:
                    failed += 1
                    await self.repo.user_block(user_id)
                except TelegramBadRequest:
                    failed += 1
                processed += 1
                after = user_id
                # Persist after each recipient: recovery replays at most the last
                # uncommitted send, rather than batches of 25 messages.
                await self.repo.broadcast_progress(job_id, processed, failed, after, "running")
                if processed % 25 == 0:
                    try:
                        await self.bot.edit_message_text(
                            self.progress_text(processed, job.total, failed, False),
                            chat_id=job.admin_id, message_id=job.progress_message_id,
                            reply_markup=broadcast_stop_keyboard(job_id),
                        )
                    except TelegramBadRequest:
                        pass
                await asyncio.sleep(0.065)
        await self.repo.broadcast_progress(job_id, processed, failed, after, "complete")
        final = await self.repo.get_broadcast(job_id)
        if final is None or final.status == "cancelled":
            return
        try:
            await self.bot.edit_message_text(
                self.progress_text(processed, job.total, failed, True),
                chat_id=job.admin_id, message_id=job.progress_message_id,
            )
        except TelegramBadRequest:
            pass

    async def consume(self, stream: str, concurrency_id: int) -> None:
        consumer = f"{self.consumer}-{concurrency_id}"
        while True:
            try:
                # Reclaim abandoned jobs after 3 minutes; live jobs renew PEL every 45s.
                stale = await self.redis.xautoclaim(
                    stream, GROUP, consumer, min_idle_time=STALE_AFTER_MS,
                    start_id="0-0", count=1,
                )
                messages = stale[1] if len(stale) > 1 else []
                if not messages:
                    entries = await self.redis.xreadgroup(
                        GROUP, consumer, {stream: ">"}, count=1, block=3000,
                    )
                    messages = entries[0][1] if entries else []
                for event_id, payload in messages:
                    job_id = payload.get("job_id")
                    if not job_id:
                        await acknowledge(self.redis, stream, event_id)
                        continue
                    try:
                        async with keep_pending_alive(self.redis, stream, consumer, event_id):
                            if stream == DOWNLOAD_STREAM:
                                await self.process_download(job_id)
                            else:
                                await self.process_broadcast(job_id)
                    except Exception:
                        # Do not ACK infrastructure failures; reclaim after timeout.
                        log.exception("Worker crashed handling %s %s", stream, job_id)
                    else:
                        await acknowledge(self.redis, stream, event_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Queue consumer error")
                await asyncio.sleep(3)

    async def run(self) -> None:
        await ensure_groups(self.redis)
        async with asyncio.TaskGroup() as group:
            for index in range(settings.worker_concurrency):
                group.create_task(self.consume(DOWNLOAD_STREAM, index))
            group.create_task(self.consume(BROADCAST_STREAM, 99))

async def main() -> None:
    logging.basicConfig(level=settings.log_level.upper(),
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    redis = make_redis()
    bot = make_bot()
    try:
        await redis.ping()
        worker = Worker(bot, redis, Repository(session_factory, redis))
        await worker.run()
    finally:
        await bot.session.close()
        await redis.aclose()
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
