from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.health import HealthStatus, health_status


class DatabaseContext:
    async def __aenter__(self):
        return SimpleNamespace(execute=AsyncMock(return_value=1))

    async def __aexit__(self, exc_type, exc, tb):
        return None


class RedisStub:
    ping = AsyncMock(return_value=True)

    async def scan_iter(self, *, match: str, count: int):
        yield "zvuk:worker:alive:worker1"


@pytest.mark.asyncio
async def test_healthy_system_reports_four_components():
    bot = SimpleNamespace(get_me=AsyncMock(return_value=SimpleNamespace(id=123)))
    repo = SimpleNamespace(factory=lambda: DatabaseContext())
    report = await health_status(bot, RedisStub(), repo)
    assert report == HealthStatus(True, True, True, True)
    assert report.display().count("✅") == 4


def test_unhealthy_report_does_not_claim_live_download():
    message = HealthStatus(False, True, False, False).display()
    assert "❌ Telegram" in message
    assert "не тест реального скачивания" in message
