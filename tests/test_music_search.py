from unittest.mock import patch

import pytest
from yt_dlp.utils import DownloadError

from app.services.music_search import (
    MusicSearch, MusicSearchError, normalize_query, parse_search_entries,
)

VID1 = "dQw4w9WgXcQ"
VID2 = "abcdefghijk"


def test_normalizes_search_terms():
    assert normalize_query("  Queen   Bohemian  Rhapsody  ") == "Queen Bohemian Rhapsody"


@pytest.mark.parametrize("query", ["a", "   ", "x" * 121, "https://example.org"])
def test_rejects_invalid_query(query):
    with pytest.raises(MusicSearchError):
        normalize_query(query)


def test_parses_safe_youtube_results_only():
    payload = {"entries": [
        {"id": VID1, "title": "Track A", "channel": "Artist", "duration": 213},
        {"id": VID1, "title": "Duplicate"},
        {"id": "short", "title": "Bad"},
        {"id": VID2, "title": "Track B", "duration": 185},
    ]}
    results = parse_search_entries(payload)
    assert len(results) == 2
    assert results[0].artist == "Artist"
    assert results[0].url == "https://www.youtube.com/watch?v=" + VID1


@pytest.mark.asyncio
async def test_search_returns_parsed_results_without_download():
    search = MusicSearch()
    with patch.object(MusicSearch, "_search_sync", return_value={
        "entries": [{"id": VID1, "title": "A good song", "duration": 120}]
    }) as mocked:
        result = await search.search("A good song")
    mocked.assert_called_once_with("A good song", 5)
    assert len(result) == 1
    assert result[0].duration == 120


@pytest.mark.asyncio
async def test_search_failure_is_user_friendly():
    search = MusicSearch()
    with patch.object(MusicSearch, "_search_sync", side_effect=DownloadError("network")):
        with pytest.raises(MusicSearchError, match="временно недоступен"):
            await search.search("some artist")
