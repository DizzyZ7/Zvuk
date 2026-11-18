from unittest.mock import AsyncMock

import pytest

from app.services.queue import BROADCAST_STREAM, DOWNLOAD_STREAM
from app.services.repository import Repository


@pytest.mark.asyncio
async def test_queue_depths():
    repo = Repository.__new__(Repository)
    repo.redis = AsyncMock()
    repo.redis.xlen.side_effect = [2, 1]
    assert await repo.queue_depths() == (2, 1)
    assert [call.args[0] for call in repo.redis.xlen.await_args_list] == [
        DOWNLOAD_STREAM, BROADCAST_STREAM
    ]
