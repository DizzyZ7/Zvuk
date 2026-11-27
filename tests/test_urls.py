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



@pytest.mark.parametrize(("raw", "name", "canonical"), [
    (
        "https://www.instagram.com/reel/DgLOE34yzwp/?lqvp=MXYzZmlU2ZjNmbWEybg%3D%3D",
        "Instagram Reels", "https://www.instagram.com/reel/DgLOE34yzwp/",
    ),
    (
        "https://instagram.com/reels/DgLOE34yzwp/?igsh=abcdef",
        "Instagram Reels", "https://www.instagram.com/reel/DgLOE34yzwp/",
    ),
    (
        "https://youtube.com/shorts/dQw4w9WgXcQ?si=track",
        "YouTube Shorts", "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    ),
    (
        "https://www.tiktok.com/@musician/video/1234567890123456789?is_from_webapp=1",
        "TikTok", "https://www.tiktok.com/@musician/video/1234567890123456789",
    ),
    (
        "https://vt.tiktok.com/ZSxxxxxx/?utm_source=share",
        "TikTok", "https://vt.tiktok.com/ZSxxxxxx",
    ),
])
def test_short_video_links_are_recognized_and_canonicalized(raw, name, canonical):
    from app.services.urls import short_video_label

    assert short_video_label(raw) == name
    assert parse_media_url(raw).url == canonical


@pytest.mark.parametrize("url", [
    "https://www.instagram.com/user.profile/",
    "https://www.tiktok.com/@musician",
    "https://www.tiktok.com/discover/songs",
    "https://www.tiktok.com/@musician/photo/12345",
])
def test_reject_non_video_social_pages(url):
    with pytest.raises(InvalidMediaURL):
        parse_media_url(url)


def test_youtube_watch_remains_user_selected_format():
    from app.services.urls import short_video_label

    assert short_video_label("https://youtube.com/watch?v=dQw4w9WgXcQ") is None
    assert short_video_label("https://youtube.com/shorts/dQw4w9WgXcQ") == "YouTube Shorts"
