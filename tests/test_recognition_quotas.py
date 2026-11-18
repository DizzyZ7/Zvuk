from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.bot.recognition import reserve_recognition
from app.services.recognition import Recognition


@pytest.mark.asyncio
async def test_quota_uses_atomic_two_key_script():
    redis = SimpleNamespace(eval=AsyncMock(return_value=0))
    assert await reserve_recognition(redis, 42, daily_limit=3, monthly_cap=300) == 0
    script, nkeys, daily, monthly, daily_lim, global_lim = redis.eval.await_args.args
    assert nkeys == 2
    assert "INCR" in script
    assert daily == "recognition:daily:42"
    assert monthly.startswith("recognition:month:")
    assert (daily_lim, global_lim) == (3, 300)


@pytest.mark.asyncio
async def test_quota_denials():
    redis = SimpleNamespace(eval=AsyncMock(side_effect=[1, 2]))
    assert await reserve_recognition(redis, 42, daily_limit=3, monthly_cap=300) == 1
    assert await reserve_recognition(redis, 42, daily_limit=3, monthly_cap=300) == 2


def test_result_has_metadata_only():
    result = Recognition(title="Example", artist="Artist")
    assert "Example" in repr(result)
