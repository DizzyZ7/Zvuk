import pytest

from app.services.urls import InvalidMediaURL, parse_media_url


@pytest.mark.parametrize("url,platform", [
    ("https://www.instagram.com/reel/Cz12345abc/", "instagram"),
    ("https://instagram.com/p/Cz12345abc/", "instagram"),
    ("https://www.pinterest.com/pin/123456789/", "pinterest"),
    ("https://pin.it/AbCdEf123", "pinterest"),
])
def test_new_sources(url, platform):
    media = parse_media_url(url)
    assert media.platform == platform


@pytest.mark.parametrize("url", [
    "https://www.instagram.com/accounts/login/",
    "https://www.pinterest.com/search/pins/?q=abc",
    "https://www.deezer.com/playlist/123",
])
def test_new_sources_refuse_non_media_urls(url):
    with pytest.raises(InvalidMediaURL):
        parse_media_url(url)
