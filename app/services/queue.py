"""Native PostgreSQL LISTEN/NOTIFY wake-ups; durable jobs live in SQL tables.

NOTIFY is only a hint, not the durable queue. A worker drains rows after
connecting and periodically checks for orphaned leases.
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

import asyncpg

from app.core.config import settings
from app.core.state import StateStore

DOWNLOAD_STREAM = "download"
BROADCAST_STREAM = "broadcast"
CHANNEL = "zvuk_jobs"

log = logging.getLogger(__name__)


def asyncpg_dsn() -> str:
    return settings.database_url.replace(
        "postgresql+asyncpg://", "postgresql://", 1,
    )


async def enqueue_download(store: StateStore, job_id: str) -> None:
    # Reservation already persists and NOTIFYs within its transaction.
    # Retained as a no-op for callers migrating from Redis Streams.
    return None


async def enqueue_broadcast(store: StateStore, job_id: str) -> None:
    return None


async def release_lock(store: StateStore, key: str, token: str) -> None:
    await store.release_lock(key, token)


async def listen_for_jobs(signal: asyncio.Event) -> AsyncIterator[None]:
    """Reconnect when needed; caller checks the database on every reconnect."""
    connection = await asyncpg.connect(dsn=asyncpg_dsn())

    def on_notify(_connection, _pid, _channel, _payload):
        signal.set()

    try:
        await connection.add_listener(CHANNEL, on_notify)
        yield
    finally:
        await connection.close()
