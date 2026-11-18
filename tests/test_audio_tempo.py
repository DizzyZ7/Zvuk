from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.bot.keyboards import format_keyboard
from app.services.media_downloader import AUDIO_KINDS, MediaDownloadError, MediaDownloader


def test_tempo_formats_available_for_audio_links():
    keyboard = format_keyboard("abc", allow_video=False)
    values = [b.callback_data for row in keyboard.inline_keyboard for b in row]
    assert values == ["fmt:abc:audio", "fmt:abc:fast", "fmt:abc:slow"]
    assert {"fast", "slow"} <= AUDIO_KINDS


def test_video_links_offer_four_formats():
    keyboard = format_keyboard("abc")
    values = [b.callback_data for row in keyboard.inline_keyboard for b in row]
    assert len(values) == 4
    assert "fmt:abc:video" in values


@pytest.mark.asyncio
async def test_tempo_conversion_uses_safe_ffmpeg_args(tmp_path: Path):
    source = tmp_path / "track.mp3"
    source.write_bytes(b"input")
    proc = SimpleNamespace(returncode=0, communicate=AsyncMock(return_value=(b"", b"")))
    async def create(*args, **kwargs):
        assert args[0] == "ffmpeg"
        assert "-filter:a" in args
        assert args[args.index("-filter:a") + 1] == "atempo=1.25"
        Path(args[-1]).write_bytes(b"output")
        return proc

    with patch("app.services.media_downloader.asyncio.create_subprocess_exec", new=create):
        dest = await MediaDownloader._shift_tempo(source, 1.25, "fast")
    assert dest.name == "track_fast.mp3"
    assert dest.read_bytes() == b"output"
    assert not source.exists()


@pytest.mark.asyncio
async def test_tempo_rejects_out_of_range(tmp_path: Path):
    source = tmp_path / "track.mp3"
    source.write_bytes(b"input")
    with pytest.raises(MediaDownloadError):
        await MediaDownloader._shift_tempo(source, 7.0, "fast")
