from unittest.mock import AsyncMock

import pytest

from app.services.repository import Repository


class FakeSession:
    def __init__(self):
        self.scalar = AsyncMock(side_effect=[2, 1])

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_queue_depths_uses_postgres_counts():
    session = FakeSession()
    repo = Repository.__new__(Repository)
    repo.factory = lambda: session
    assert await repo.queue_depths() == (2, 1)
    assert session.scalar.await_count == 2
