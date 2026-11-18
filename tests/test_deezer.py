from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.deezer_resolver import DeezerResolver, DeezerResolutionError
from app.services.urls import InvalidMediaURL, parse_media_url


@pytest.mark.parametrize("url", [
    "https://deezer.com/track/3135556",
    "https://www.deezer.com/en/track/3135556?utm_source=abc",
])
def test_deezer_normalizes_link(url):
    media = parse_media_url(url)
    assert media.default_kind == "audio"
    assert media.url == "https://www.deezer.com/track/3135556"


def test_deezer_refuses_album_link():
    with pytest.raises(InvalidMediaURL):
        parse_media_url("https://www.deezer.com/album/123")


@pytest.mark.asyncio
async def test_deezer_resolver_uses_public_metadata():
    media = parse_media_url("https://www.deezer.com/track/3135556")
    response = MagicMock(status=200)
    response.json = AsyncMock(return_value={
        "title": "Harder, Better, Faster, Stronger",
        "artist": {"name": "Daft Punk"},
    })
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=None)
    session = MagicMock()
    session.get.return_value = response
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    with patch("app.services.deezer_resolver.aiohttp.ClientSession", return_value=session):
        query = await DeezerResolver().search_query(media)
    assert query.startswith("ytsearch1:Daft Punk - Harder")
    session.get.assert_called_once_with(
        "https://api.deezer.com/track/3135556", allow_redirects=False,
    )


@pytest.mark.asyncio
async def test_deezer_error_is_explicit():
    media = parse_media_url("https://deezer.com/track/1")
    response = MagicMock(status=404)
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=None)
    session = MagicMock()
    session.get.return_value = response
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    with patch("app.services.deezer_resolver.aiohttp.ClientSession", return_value=session):
        with pytest.raises(DeezerResolutionError):
            await DeezerResolver().search_query(media)
