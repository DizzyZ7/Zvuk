"""No internet calls: exercise the single-download dual-output contract."""
import tempfile
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.media_downloader import DownloadedMedia, MediaDownloader
from app.services.urls import cache_key, parse_media_url
from app.worker import Worker


def job(id="job01", user_id=42, url="https://www.instagram.com/reel/DgLOE34yzwp/"):
    media = parse_media_url(url)
    return SimpleNamespace(
        id=id, user_id=user_id, url=media.url,
        cache_key=cache_key(media, "clip"), kind="clip", status="processing",
    )


def make_worker(cache_ids=None, statuses=None):
    repo = SimpleNamespace(
        factory=None,
        download_states=AsyncMock(return_value=statuses or {}),
        cache_get=AsyncMock(side_effect=cache_ids if cache_ids is not None else [None, None]),
        cache_put=AsyncMock(),
        record_delivered_output=AsyncMock(),
        update_download=AsyncMock(),
    )
    @asynccontextmanager
    async def unlocked(_key):
        yield

    redis = SimpleNamespace(media_lock=unlocked)
    bot = SimpleNamespace(send_message=AsyncMock())
    worker = Worker(bot, redis, repo)
    worker.send_media = AsyncMock(side_effect=["tg-video-id", "tg-audio-id"])
    worker.send_cached = AsyncMock()
    return worker


@pytest.mark.asyncio
async def test_short_video_downloaded_once_and_sent_video_before_mp3(tmp_path):
    worker = make_worker()
    video_fetches = []

    async def fake_download(media, kind, folder, **kwargs):
        assert kind == "video"
        video_fetches.append(media.url)
        path = folder / "source.mp4"
        path.write_bytes(b"video")
        return DownloadedMedia(path=path, title="Animals", performer=None, duration=90)

    async def fake_extract(video, folder):
        path = folder / "track.mp3"
        path.write_bytes(b"audio")
        return DownloadedMedia(path=path, title=video.title,
                               performer=None, duration=video.duration)

    worker.downloader.download = AsyncMock(side_effect=fake_download)
    worker.downloader.extract_video_sound = AsyncMock(side_effect=fake_extract)
    original = tempfile.TemporaryDirectory
    with patch("app.worker.tempfile.TemporaryDirectory",
               side_effect=lambda **kw: original(dir=tmp_path)):
        await worker._deliver_short_clip(job())

    assert len(video_fetches) == 1
    assert worker.send_media.await_count == 2
    calls = worker.send_media.await_args_list
    assert [call.args[1] for call in calls] == ["video", "audio"]
    assert calls[0].kwargs["show_ads"] is True
    assert calls[1].kwargs["show_ads"] is False
    assert worker.repo.cache_put.await_count == 2
    assert worker.repo.record_delivered_output.await_count == 2
    worker.repo.update_download.assert_awaited_once_with(
        "job01", "success", cache_hit=False,
    )


@pytest.mark.asyncio
async def test_second_user_reuses_both_cached_outputs_without_site_request(tmp_path):
    worker = make_worker(cache_ids=["existing-video", "existing-audio"])
    worker.downloader.download = AsyncMock()
    original = tempfile.TemporaryDirectory
    with patch("app.worker.tempfile.TemporaryDirectory",
               side_effect=lambda **kw: original(dir=tmp_path)):
        await worker._deliver_short_clip(job(user_id=99))

    assert worker.send_cached.await_count == 2
    assert [call.args[1] for call in worker.send_cached.await_args_list] == [
        "video", "audio",
    ]
    assert worker.send_cached.await_args_list[1].kwargs["show_ads"] is False
    worker.downloader.download.assert_not_awaited()
    worker.repo.update_download.assert_awaited_once_with(
        "job01", "success", cache_hit=True,
    )


@pytest.mark.asyncio
async def test_retry_only_sends_missing_audio_after_video_success(tmp_path):
    target = job()
    video_key = cache_key(parse_media_url(target.url), "video")
    worker = make_worker(
        cache_ids=["video-cached", None],
        statuses={video_key: "success"},
    )

    async def video_from_telegram(file_id, folder):
        path = folder / "cached.mp4"
        path.write_bytes(b"video")
        return DownloadedMedia(path=path, title="From Telegram",
                               performer=None, duration=50)

    async def audio_from_video(video, folder):
        path = folder / "music.mp3"
        path.write_bytes(b"audio")
        return DownloadedMedia(path=path, title=video.title,
                               performer=None, duration=video.duration)

    worker._clip_video_from_cache = AsyncMock(side_effect=video_from_telegram)
    worker.downloader.extract_video_sound = AsyncMock(side_effect=audio_from_video)
    worker.downloader.download = AsyncMock()
    worker.send_media = AsyncMock(return_value="audio-id")
    original = tempfile.TemporaryDirectory
    with patch("app.worker.tempfile.TemporaryDirectory",
               side_effect=lambda **kw: original(dir=tmp_path)):
        await worker._deliver_short_clip(target)

    worker.send_cached.assert_not_awaited()
    worker.downloader.download.assert_not_awaited()
    worker.send_media.assert_awaited_once()
    assert worker.send_media.await_args.args[1] == "audio"
    assert worker.repo.record_delivered_output.await_count == 1


@pytest.mark.asyncio
async def test_silent_video_delivers_video_and_explains_missing_mp3(tmp_path):
    worker = make_worker()
    async def fake_download(media, kind, folder, **kwargs):
        path = folder / "silent.mp4"
        path.write_bytes(b"video")
        return DownloadedMedia(path=path, title="Silent", performer=None, duration=45)

    worker.downloader.download = AsyncMock(side_effect=fake_download)
    worker.downloader.extract_video_sound = AsyncMock(return_value=None)
    original = tempfile.TemporaryDirectory
    with patch("app.worker.tempfile.TemporaryDirectory",
               side_effect=lambda **kw: original(dir=tmp_path)):
        await worker._deliver_short_clip(job())

    worker.send_media.assert_awaited_once()
    assert worker.send_media.await_args.args[1] == "video"
    assert worker.repo.record_delivered_output.await_count == 1
    assert "звуковой дорожки" in worker.bot.send_message.await_args.args[1]


@pytest.mark.asyncio
async def test_no_audio_stream_ffmpeg_is_not_treated_as_provider_error(tmp_path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"mockvideo")
    proc = SimpleNamespace(
        returncode=1,
        communicate=AsyncMock(return_value=(
            b"", b"Stream map '0:a:0' matches no streams.",
        )),
    )
    with patch("app.services.media_downloader.asyncio.create_subprocess_exec",
               new=AsyncMock(return_value=proc)):
        downloader = MediaDownloader(SimpleNamespace(
            max_file_mb=150, proxy_list=(), ytdlp_cookies="",
            spotify_client_id="", spotify_client_secret="",
        ))
        result = await downloader.extract_video_sound(
            DownloadedMedia(path=video, title="Test", performer=None, duration=None),
            tmp_path,
        )
    assert result is None
