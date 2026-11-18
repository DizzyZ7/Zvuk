"""Reliable Redis Streams delivery and distributed media locks."""
import asyncio
import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from redis.asyncio import Redis
from redis.exceptions import ResponseError

DOWNLOAD_STREAM = "zvuk:downloads"
BROADCAST_STREAM = "zvuk:broadcasts"
GROUP = "workers"
HEARTBEAT_SECONDS = 45
STALE_AFTER_MS = 180_000

log = logging.getLogger(__name__)


async def ensure_groups(redis: Redis) -> None:
    for stream in (DOWNLOAD_STREAM, BROADCAST_STREAM):
        try:
            await redis.xgroup_create(stream, GROUP, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise


async def enqueue_download(redis: Redis, job_id: str) -> None:
    await redis.xadd(DOWNLOAD_STREAM, {"job_id": job_id})


async def enqueue_broadcast(redis: Redis, job_id: str) -> None:
    await redis.xadd(BROADCAST_STREAM, {"job_id": job_id})


async def acknowledge(redis: Redis, stream: str, event_id: str) -> None:
    """A single consumer group owns these streams: ACK then delete confirmed events."""
    if await redis.xack(stream, GROUP, event_id):
        try:
            await redis.xdel(stream, event_id)
        except Exception:
            # A deleted-but-unacknowledged entry would lose work. Reverse order is unsafe.
            # An acknowledged entry left in the stream is harmless; surface for monitoring.
            log.exception("Failed to remove ACKed stream event %s:%s", stream, event_id)


@asynccontextmanager
async def keep_pending_alive(
    redis: Redis, stream: str, consumer: str, event_id: str,
) -> AsyncIterator[None]:
    """Renew PEL idle time so a healthy slow download is not reclaimed by another worker."""
    async def heartbeat() -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            try:
                claimed = await redis.xclaim(
                    stream, GROUP, consumer, min_idle_time=0,
                    message_ids=[event_id], justid=True,
                )
                if not claimed:
                    log.warning("Stream event disappeared before ACK: %s:%s", stream, event_id)
                    return
            except asyncio.CancelledError:
                raise
            except Exception:
                # Processing continues; if Redis stays unavailable, this event can be
                # reclaimed. Backend jobs are at-least-once, not exactly-once.
                log.exception("Stream heartbeat failed: %s:%s", stream, event_id)

    task = asyncio.create_task(heartbeat(), name=f"stream-heartbeat:{event_id}")
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def release_lock(redis: Redis, key: str, token: str) -> None:
    await redis.eval(
        "if redis.call('get',KEYS[1]) == ARGV[1] then "
        "return redis.call('del',KEYS[1]) else return 0 end",
        1, key, token,
    )
