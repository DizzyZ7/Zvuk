from unittest.mock import AsyncMock, patch

import pytest
from yt_dlp.utils import DownloadError

from app.core.config import settings
from app.services.media_downloader import MediaDownloader
from app.services.urls import parse_media_url


@pytest.mark.parametrize("error", [
    "HTTP Error 503: Service Unavailable",
    "Connection reset by peer",
    "Read timed out",
    "remote end closed connection",
])
def test_retries_transient_issues(error):
    assert MediaDownloader._should_retry(error)


@pytest.mark.parametrize("error", [
    "HTTP Error 429: Too Many Requests",
    "Sign in to confirm you're not a bot",
    "This video is private",
    "Login required",
    "MAX_DURATION_EXCEEDED",
    "Unsupported URL",
])
def test_does_not_hammer_restricted_or_permanent_failures(error):
    assert not MediaDownloader._should_retry(error)


def test_bot_check_is_not_misreported_as_private_video():
    text = MediaDownloader._human_error("Sign in to confirm you're not a bot")
    assert "ограничил" in text
    assert "приватный" not in text


def test_private_status_is_not_claimed_certain():
    text = MediaDownloader._human_error("Private video")
    assert "не предоставил доступ" in text
    assert "попробуйте позже" in text


@pytest.mark.asyncio
async def test_transient_youtube_error_retries_once_then_returns_file(tmp_path):
    downloader = MediaDownloader(settings)
    (tmp_path / "track.mp3").write_bytes(b"test media")
    target = parse_media_url("https://youtu.be/dQw4w9WgXcQ")
    with patch.object(MediaDownloader, "_run_ytdlp",
                      side_effect=[DownloadError("HTTP Error 503"), {"title": "Demo"}]) as run:
        with patch("app.services.media_downloader.asyncio.sleep", new_callable=AsyncMock):
            output = await downloader.download(target, "audio", tmp_path)
    assert output.title == "Demo"
    assert run.call_count == 2


@pytest.mark.asyncio
async def test_private_video_is_not_retried(tmp_path):
    downloader = MediaDownloader(settings)
    target = parse_media_url("https://youtu.be/dQw4w9WgXcQ")
    with patch.object(MediaDownloader, "_run_ytdlp",
                      side_effect=DownloadError("This video is private")) as run:
        with pytest.raises(Exception, match="не предоставил доступ"):
            await downloader.download(target, "audio", tmp_path)
    assert run.call_count == 1
