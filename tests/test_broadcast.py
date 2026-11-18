from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.worker import Worker


@pytest.mark.asyncio
async def test_broadcast_does_not_send_when_cancelled():
    repo = SimpleNamespace(get_broadcast=AsyncMock(return_value=SimpleNamespace(status="cancelled")))
    worker = Worker.__new__(Worker)
    worker.repo = repo
    worker.bot = AsyncMock()
    await worker.process_broadcast("a" * 32)
    worker.bot.copy_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_broadcast_persists_every_recipient():
    job = SimpleNamespace(
        status="running", processed=0, failed=0, last_user_id=0,
        source_chat_id=7, source_message_id=9, progress_message_id=10,
        admin_id=7, total=2, created_at=datetime.now(timezone.utc),
    )
    repo = SimpleNamespace(
        get_broadcast=AsyncMock(return_value=job),
        users_after=AsyncMock(side_effect=[[101, 102], []]),
        broadcast_progress=AsyncMock(),
    )
    worker = Worker.__new__(Worker)
    worker.repo = repo
    worker.bot = AsyncMock()
    await worker.process_broadcast("b" * 32)
    assert worker.bot.copy_message.await_count == 2
    assert repo.broadcast_progress.await_count == 3
    assert [call.args[1] for call in repo.broadcast_progress.await_args_list] == [1, 2, 2]
    assert repo.broadcast_progress.await_args_list[-1].args[-1] == "complete"
    assert repo.users_after.await_args_list[0].kwargs["created_before"] == job.created_at
