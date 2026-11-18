from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from redis.exceptions import ConnectionError

from app.worker import Worker


def make_worker(retry_count: int):
    job = SimpleNamespace(
        id="job", user_id=777, status="queued", cache_key="key", kind="audio",
    )
    repo = SimpleNamespace(
        download=AsyncMock(return_value=job),
        update_download=AsyncMock(),
        cache_get=AsyncMock(side_effect=ConnectionError("temporary Redis failure")),
        record_download_retry=AsyncMock(return_value=retry_count),
    )
    worker = Worker.__new__(Worker)
    worker.repo = repo
    worker.redis = AsyncMock()
    worker.bot = AsyncMock()
    worker.ads = SimpleNamespace(caption=AsyncMock(return_value=""))
    return worker, repo


@pytest.mark.asyncio
async def test_transient_redis_error_is_retried():
    worker, repo = make_worker(retry_count=1)
    with pytest.raises(ConnectionError):
        await worker.process_download("job")
    assert repo.record_download_retry.await_count == 1
    assert not any(call.args[1] == "failed" for call in repo.update_download.await_args_list)


@pytest.mark.asyncio
async def test_retry_budget_exhaustion_notifies_user():
    worker, repo = make_worker(retry_count=4)
    await worker.process_download("job")
    repo.update_download.assert_any_await(
        "job", "failed",
        error="Сервис временно недоступен после нескольких попыток. Повторите запрос позже.",
    )
    worker.bot.send_message.assert_awaited_once()
