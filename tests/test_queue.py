from unittest.mock import AsyncMock

import pytest

from app.services.queue import (
    BROADCAST_STREAM, CHANNEL, DOWNLOAD_STREAM, asyncpg_dsn,
    enqueue_broadcast, enqueue_download, release_lock,
)


@pytest.mark.asyncio
async def test_legacy_enqueue_is_noop_after_transactional_sql_notify():
    state = AsyncMock()
    await enqueue_download(state, "job-id")
    await enqueue_broadcast(state, "broadcast-id")
    state.assert_not_awaited()
    assert DOWNLOAD_STREAM == "download"
    assert BROADCAST_STREAM == "broadcast"
    assert CHANNEL == "zvuk_jobs"


@pytest.mark.asyncio
async def test_release_lock_is_token_guarded_by_postgres():
    state = AsyncMock()
    await release_lock(state, "media-lock:abc", "owned")
    state.release_lock.assert_awaited_once_with("media-lock:abc", "owned")


def test_asyncpg_dsn_has_native_scheme():
    from unittest.mock import patch

    with patch("app.services.queue.settings") as settings:
        settings.database_url = "postgresql+asyncpg://test:pwd@localhost:5432/zvuk"
        assert asyncpg_dsn() == "postgresql://test:pwd@localhost:5432/zvuk"
