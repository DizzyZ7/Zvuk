import pytest
from app.services.urls import InvalidMediaURL, cache_key, find_media_url, parse_media_url

def test_youtube_short_and_watch_canonicalize():
    a = parse_media_url("https://youtu.be/dQw4w9WgXcQ?si=abc")
    b = parse_media_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert a == b
    assert cache_key(a, "audio") != cache_key(a, "video")
    assert cache_key(a, "audio", owner_id=1) != cache_key(a, "audio", owner_id=2)

def test_spotify_is_audio_only():
    media = parse_media_url("https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC?si=x")
    assert media.default_kind == "audio"
    assert media.url == "https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC"

@pytest.mark.parametrize("url", [
    "https://127.0.0.1/internal", "https://evil.com/?q=youtube.com",
    "file:///etc/passwd", "https://user:pass@youtube.com/watch?v=dQw4w9WgXcQ",
    "http://localhost/", "https://open.spotify.com/playlist/abcd",
])
def test_reject_unsafe_or_unsupported(url: str):
    with pytest.raises(InvalidMediaURL):
        parse_media_url(url)

def test_find_link_in_message():
    assert find_media_url("Try https://rutube.ru/video/1234/") is not None
