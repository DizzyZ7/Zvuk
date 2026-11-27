from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.bot.handlers import dispatch_download, download_status_message
from app.core.config import settings
from app.services.urls import parse_media_url


def media():
    return parse_media_url("https://youtu.be/dQw4w9WgXcQ")


@pytest.mark.asyncio
async def test_previously_downloaded_rejected_before_queue_processing():
    repo = SimpleNamespace(
        reserve_download=AsyncMock(return_value=("downloaded", None)),
        cache_get=AsyncMock(), update_download=AsyncMock(),
    )
    bot, state, ads = AsyncMock(), AsyncMock(), AsyncMock()
    result = await dispatch_download(bot, 42, 42, media(), "audio",
                                     repo, state, ads, settings,
                                     notify_rejection=False)
    assert result == "downloaded"
    repo.cache_get.assert_not_awaited()
    bot.send_audio.assert_not_awaited()
    repo.update_download.assert_not_awaited()


@pytest.mark.asyncio
async def test_cache_hits_are_handled_only_by_worker_not_by_bot():
    repo = SimpleNamespace(
        reserve_download=AsyncMock(return_value=("reserved", "job01")),
        cache_get=AsyncMock(return_value="cached-id"),
        update_download=AsyncMock(),
    )
    bot, state, ads = AsyncMock(), AsyncMock(), AsyncMock()
    result = await dispatch_download(bot, 42, 42, media(), "audio",
                                     repo, state, ads, settings)
    assert result == "queued"
    repo.cache_get.assert_not_awaited()
    bot.send_audio.assert_not_awaited()
    repo.update_download.assert_not_awaited()
    bot.send_message.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("result", ["pending", "limit"])
async def test_pending_and_limit_short_circuit(result):
    repo = SimpleNamespace(
        reserve_download=AsyncMock(return_value=(result, None)),
        cache_get=AsyncMock(),
    )
    bot = AsyncMock()
    status = await dispatch_download(
        bot, 42, 42, media(), "audio", repo,
        AsyncMock(), AsyncMock(), settings,
    )
    assert status == result
    repo.cache_get.assert_not_awaited()
    bot.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_new_job_is_durable_before_status_reply():
    repo = SimpleNamespace(
        reserve_download=AsyncMock(return_value=("reserved", "job-2")),
    )
    bot = AsyncMock()
    bot.send_message.side_effect = ConnectionError("status message failed")
    with pytest.raises(ConnectionError):
        await dispatch_download(
            bot, 42, 42, media(), "audio",
            repo, AsyncMock(), AsyncMock(), settings,
        )
    # Queue reservation already committed and notified in repo transaction.
    repo.reserve_download.assert_awaited_once()


@pytest.mark.asyncio
async def test_short_video_link_starts_one_dual_output_job_without_picker():
    from app.bot.handlers import handle_link

    message = SimpleNamespace(
        from_user=SimpleNamespace(id=42),
        chat=SimpleNamespace(id=42),
        text="https://www.instagram.com/reel/DgLOE34yzwp/?lqvp=tracking",
        answer=AsyncMock(),
    )
    repo = SimpleNamespace(
        reserve_clip_download=AsyncMock(return_value=("reserved", "job-clip")),
        cache_get=AsyncMock(),
    )
    bot = AsyncMock()
    await handle_link(
        message, bot, AsyncMock(), repo,
        SimpleNamespace(register=AsyncMock()), AsyncMock(), settings,
        SimpleNamespace(search=AsyncMock()),
    )
    repo.reserve_clip_download.assert_awaited_once()
    repo.cache_get.assert_not_awaited()
    message.answer.assert_not_awaited()
    assert "MP3" in bot.send_message.await_args.args[1]


@pytest.mark.asyncio
async def test_shorts_keep_deduplication():
    from app.bot.handlers import handle_link

    message = SimpleNamespace(
        from_user=SimpleNamespace(id=42),
        chat=SimpleNamespace(id=42),
        text="https://www.youtube.com/shorts/dQw4w9WgXcQ?si=abc",
        answer=AsyncMock(),
    )
    repo = SimpleNamespace(
        reserve_clip_download=AsyncMock(return_value=("pending", None)),
        cache_get=AsyncMock(),
    )
    bot = AsyncMock()
    await handle_link(
        message, bot, AsyncMock(), repo,
        SimpleNamespace(register=AsyncMock()), AsyncMock(), settings,
        SimpleNamespace(search=AsyncMock()),
    )
    assert "уже" in bot.send_message.await_args.args[1]


@pytest.mark.asyncio
async def test_normal_watch_url_shows_format_picker():
    from app.bot.handlers import handle_link

    message = SimpleNamespace(
        from_user=SimpleNamespace(id=42),
        chat=SimpleNamespace(id=42),
        text="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        answer=AsyncMock(),
    )
    repo, state, bot = AsyncMock(), AsyncMock(), AsyncMock()
    await handle_link(
        message, bot, state, repo,
        SimpleNamespace(register=AsyncMock()), AsyncMock(), settings,
        SimpleNamespace(search=AsyncMock()),
    )
    state.set.assert_awaited_once()
    message.answer.assert_awaited_once()
    assert message.answer.await_args.kwargs["reply_markup"]


def test_rejection_messages():
    assert "уже получал" in download_status_message("downloaded", settings)
    assert "уже скачивается" in download_status_message("pending", settings)
