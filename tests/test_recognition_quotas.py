from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.bot.recognition import reserve_recognition
from app.services.recognition import Recognition


@pytest.mark.asyncio
async def test_quota_uses_postgres_atomic_method():
    state = SimpleNamespace(reserve_recognition=AsyncMock(return_value=0))
    assert await reserve_recognition(state, 42, daily_limit=3, monthly_cap=300) == 0
    state.reserve_recognition.assert_awaited_once_with(
        42, daily_limit=3, monthly_cap=300,
    )


@pytest.mark.asyncio
async def test_quota_denials():
    state = SimpleNamespace(reserve_recognition=AsyncMock(side_effect=[1, 2]))
    assert await reserve_recognition(state, 42, daily_limit=3, monthly_cap=300) == 1
    assert await reserve_recognition(state, 42, daily_limit=3, monthly_cap=300) == 2


def test_result_has_metadata_only():
    result = Recognition(title="Example", artist="Artist")
    assert "Example" in repr(result)
