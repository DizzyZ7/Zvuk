import asyncio
from unittest.mock import AsyncMock

import pytest

from app.services.queue import (
    BROADCAST_STREAM, DOWNLOAD_STREAM, GROUP, acknowledge, keep_pending_alive,
)


@pytest.mark.asyncio
async def test_acknowledge_removes_processed_event():
    redis = AsyncMock()
    redis.xack.return_value = 1
    await acknowledge(redis, DOWNLOAD_STREAM, "123-0")
    redis.xack.assert_awaited_once_with(DOWNLOAD_STREAM, GROUP, "123-0")
    redis.xdel.assert_awaited_once_with(DOWNLOAD_STREAM, "123-0")


@pytest.mark.asyncio
async def test_acknowledge_does_not_delete_unacknowledged_event():
    redis = AsyncMock()
    redis.xack.return_value = 0
    await acknowledge(redis, BROADCAST_STREAM, "123-0")
    redis.xdel.assert_not_awaited()


@pytest.mark.asyncio
async def test_keep_pending_alive_cancels_heartbeat_on_exit():
    redis = AsyncMock()
    async with keep_pending_alive(redis, DOWNLOAD_STREAM, "c1", "123-0"):
        await asyncio.sleep(0)
    # No pending background tasks survive the context manager.
    assert not any(
        t.get_name() == "stream-heartbeat:123-0" and not t.done()
        for t in asyncio.all_tasks()
    )
