from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.bot.handlers import dispatch_download, download_status_message
from app.core.config import settings
from app.services.urls import parse_media_url


def media():
    return parse_media_url("https://youtu.be/dQw4w9WgXcQ")


@pytest.mark.asyncio
async def test_previously_downloaded_rejected_before_redis_or_media_cache():
    repo = SimpleNamespace(
        reserve_download=AsyncMock(return_value=("downloaded", None)),
        cache_get=AsyncMock(), update_download=AsyncMock(),
    )
    bot, redis, ads = AsyncMock(), AsyncMock(), AsyncMock()
    result = await dispatch_download(bot, 42, 42, media(), "audio",
                                     repo, redis, ads, settings,
                                     notify_rejection=False)
    assert result == "downloaded"
    repo.cache_get.assert_not_awaited()
    bot.send_audio.assert_not_awaited()
    redis.xadd.assert_not_awaited()
    repo.update_download.assert_not_awaited()


@pytest.mark.asyncio
async def test_cached_file_is_sent_once_and_marked_success():
    repo = SimpleNamespace(
        reserve_download=AsyncMock(return_value=("reserved", "job01")),
        cache_get=AsyncMock(return_value="file_id_cached"),
        update_download=AsyncMock(),
    )
    bot, redis, ads = AsyncMock(), AsyncMock(), SimpleNamespace(
        placement=AsyncMock(return_value=SimpleNamespace(caption="ad")),
        delivered=AsyncMock(),
    )
    result = await dispatch_download(bot, 42, 42, media(), "audio",
                                     repo, redis, ads, settings)
    assert result == "cached"
    bot.send_audio.assert_awaited_once()
    repo.update_download.assert_awaited_once_with("job01", "success", cache_hit=True)
    ads.delivered.assert_awaited_once()
    redis.xadd.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["pending", "limit"])
async def test_pending_and_queue_limit_short_circuit(state):
    repo = SimpleNamespace(
        reserve_download=AsyncMock(return_value=(state, None)),
        cache_get=AsyncMock(),
    )
    bot, redis = AsyncMock(), AsyncMock()
    result = await dispatch_download(bot, 42, 42, media(), "audio",
                                     repo, redis, AsyncMock(), settings)
    assert result == state
    repo.cache_get.assert_not_awaited()
    bot.send_message.assert_awaited_once()
    redis.xadd.assert_not_awaited()


@pytest.mark.asyncio
async def test_first_time_cache_miss_queues_once():
    repo = SimpleNamespace(
        reserve_download=AsyncMock(return_value=("reserved", "job02")),
        cache_get=AsyncMock(return_value=None),
        update_download=AsyncMock(),
    )
    bot, redis = AsyncMock(), AsyncMock()
    result = await dispatch_download(bot, 42, 42, media(), "video",
                                     repo, redis, AsyncMock(), settings)
    assert result == "queued"
    redis.xadd.assert_awaited_once_with(
        "zvuk:downloads", {"job_id": "job02"},
    )
    bot.send_message.assert_awaited_once()
    repo.reserve_download.assert_awaited_once()


@pytest.mark.asyncio
async def test_redis_queue_failure_releases_database_reservation():
    repo = SimpleNamespace(
        reserve_download=AsyncMock(return_value=("reserved", "job03")),
        cache_get=AsyncMock(return_value=None),
        update_download=AsyncMock(),
    )
    bot, redis = AsyncMock(), AsyncMock()
    redis.xadd.side_effect = ConnectionError("redis unavailable")
    with pytest.raises(ConnectionError):
        await dispatch_download(bot, 42, 42, media(), "audio",
                                repo, redis, AsyncMock(), settings)
    repo.update_download.assert_awaited_once()
    assert repo.update_download.await_args.args[:2] == ("job03", "failed")


def test_friendly_rejection_messages():
    assert "уже получал" in download_status_message("downloaded", settings)
    assert "уже скачивается" in download_status_message("pending", settings)
    assert "ожидающих" in download_status_message("limit", settings)



@pytest.mark.asyncio
async def test_short_video_link_starts_one_dual_output_job_without_format_picker():
    from app.bot.handlers import handle_link

    message = SimpleNamespace(
        from_user=SimpleNamespace(id=42),
        chat=SimpleNamespace(id=42),
        text=(
            "https://www.instagram.com/reel/DgLOE34yzwp/"
            "?lqvp=MXYzZmlU2ZjNmbWEybg%3D%3D"
        ),
        answer=AsyncMock(),
    )
    bot, redis = AsyncMock(), AsyncMock()
    repo = SimpleNamespace(
        reserve_clip_download=AsyncMock(return_value=("reserved", "job-clip")),
        update_download=AsyncMock(),
        cache_get=AsyncMock(),
    )
    await handle_link(
        message, bot, redis, repo,
        SimpleNamespace(register=AsyncMock()), AsyncMock(), settings,
        SimpleNamespace(search=AsyncMock()),
    )
    repo.reserve_clip_download.assert_awaited_once()
    assert repo.reserve_clip_download.await_args.args[1] == (
        "https://www.instagram.com/reel/DgLOE34yzwp/"
    )
    redis.xadd.assert_awaited_once()
    message.answer.assert_not_awaited()
    repo.cache_get.assert_not_awaited()
    assert "MP3" in bot.send_message.await_args.args[1]


@pytest.mark.asyncio
async def test_shorts_go_directly_to_video_and_mp3_without_manual_format():
    from app.bot.handlers import handle_link

    message = SimpleNamespace(
        from_user=SimpleNamespace(id=42),
        chat=SimpleNamespace(id=42),
        text="https://www.youtube.com/shorts/dQw4w9WgXcQ?si=123",
        answer=AsyncMock(),
    )
    repo = SimpleNamespace(
        reserve_clip_download=AsyncMock(return_value=("pending", None)),
        cache_get=AsyncMock(),
    )
    redis = AsyncMock()
    bot = AsyncMock()
    await handle_link(
        message, bot, redis, repo,
        SimpleNamespace(register=AsyncMock()), AsyncMock(), settings,
        SimpleNamespace(search=AsyncMock()),
    )
    repo.reserve_clip_download.assert_awaited_once()
    repo.cache_get.assert_not_awaited()
    redis.xadd.assert_not_awaited()
    assert "уже" in bot.send_message.await_args.args[1]


@pytest.mark.asyncio
async def test_full_youtube_watch_keeps_manual_format_picker():
    from app.bot.handlers import handle_link

    message = SimpleNamespace(
        from_user=SimpleNamespace(id=42),
        chat=SimpleNamespace(id=42),
        text="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        answer=AsyncMock(),
    )
    repo, redis, bot = AsyncMock(), AsyncMock(), AsyncMock()
    await handle_link(
        message, bot, redis, repo,
        SimpleNamespace(register=AsyncMock()), AsyncMock(), settings,
        SimpleNamespace(search=AsyncMock()),
    )
    redis.set.assert_awaited_once()
    message.answer.assert_awaited_once()
    assert message.answer.await_args.kwargs["reply_markup"]
    repo.reserve_clip_download.assert_not_awaited()



@pytest.mark.asyncio
async def test_short_clip_job_remains_queued_if_telegram_acknowledgement_fails():
    repo = SimpleNamespace(
        reserve_clip_download=AsyncMock(return_value=("reserved", "clip-99")),
        update_download=AsyncMock(),
        cache_get=AsyncMock(),
    )
    bot = AsyncMock()
    bot.send_message.side_effect = ConnectionError("Telegram connection dropped")
    redis = AsyncMock()
    with pytest.raises(ConnectionError):
        await dispatch_download(
            bot, 42, 42,
            parse_media_url("https://www.instagram.com/reel/DgLOE34yzwp/"),
            "clip", repo, redis, AsyncMock(), settings,
        )
    redis.xadd.assert_awaited_once_with(
        "zvuk:downloads", {"job_id": "clip-99"},
    )
    # A failed confirmation message must not cancel an already-enqueued job.
    repo.update_download.assert_not_awaited()
