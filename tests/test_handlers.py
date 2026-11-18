from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.bot.handlers import dispatch_download
from app.core.config import settings
from app.services.urls import parse_media_url


@pytest.mark.asyncio
async def test_cache_reuse_records_history_and_avoids_queue():
    repo = SimpleNamespace(
        cache_get=AsyncMock(return_value="file_id_cached"),
        new_download=AsyncMock(return_value="job01"),
        update_download=AsyncMock(),
    )
    bot, redis, ads = AsyncMock(), AsyncMock(), SimpleNamespace(
        placement=AsyncMock(return_value=SimpleNamespace(caption="ad", campaign_id=2)),
        delivered=AsyncMock(),
    )
    await dispatch_download(
        bot, 42, 42, parse_media_url("https://youtu.be/dQw4w9WgXcQ"),
        "audio", repo, redis, ads, settings,
    )
    bot.send_audio.assert_awaited_once()
    repo.update_download.assert_awaited_once_with("job01", "success", cache_hit=True)
    ads.delivered.assert_awaited_once()
    redis.xadd.assert_not_awaited()


@pytest.mark.asyncio
async def test_limit_pending_downloads_before_queueing():
    repo = SimpleNamespace(
        cache_get=AsyncMock(return_value=None),
        pending_downloads=AsyncMock(return_value=settings.max_pending_per_user),
        new_download=AsyncMock(),
    )
    bot, redis = AsyncMock(), AsyncMock()
    ads = SimpleNamespace(caption=AsyncMock(return_value=None))
    await dispatch_download(
        bot, 42, 42, parse_media_url("https://youtu.be/dQw4w9WgXcQ"),
        "video", repo, redis, ads, settings,
    )
    repo.new_download.assert_not_awaited()
    bot.send_message.assert_awaited_once()
    redis.xadd.assert_not_awaited()


@pytest.mark.asyncio
async def test_miss_is_queued():
    repo = SimpleNamespace(
        cache_get=AsyncMock(return_value=None),
        pending_downloads=AsyncMock(return_value=0),
        new_download=AsyncMock(return_value="job02"),
        update_download=AsyncMock(),
    )
    bot, redis = AsyncMock(), AsyncMock()
    ads = SimpleNamespace(caption=AsyncMock(return_value=None))
    await dispatch_download(
        bot, 42, 42, parse_media_url("https://youtu.be/dQw4w9WgXcQ"),
        "video", repo, redis, ads, settings,
    )
    repo.new_download.assert_awaited_once()
    redis.xadd.assert_awaited_once_with("zvuk:downloads", {"job_id": "job02"})
    bot.send_message.assert_awaited_once()
