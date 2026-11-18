import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.bot.keyboards import search_keyboard
from app.bot.search_ui import render_search
from app.services.music_search import SearchResult
from app.services.search_sessions import (
    PAGE_SIZE, SEARCH_TTL_SECONDS, SearchSessionError,
    create_search, read_search,
)


def song(i: int) -> SearchResult:
    return SearchResult(
        title=f"Song {i}", artist="Artist",
        url=f"https://www.youtube.com/watch?v={i:011d}", duration=180,
    )


@pytest.mark.asyncio
async def test_search_one_redis_key_even_for_ten_tracks():
    redis = SimpleNamespace(set=AsyncMock(), get=AsyncMock())
    results = [song(i) for i in range(10)]
    token = await create_search(redis, 42, results, query="Lil Peep")
    assert len(token) == 16
    key, payload = redis.set.await_args.args
    assert key == f"search:{token}"
    assert redis.set.await_args.kwargs["ex"] == SEARCH_TTL_SECONDS
    redis.get.return_value = payload
    first = await read_search(redis, token, 42)
    second = await read_search(redis, token, 42)
    assert len(first.results) == 10
    assert first.results == second.results
    assert first.query == "Lil Peep"
    assert redis.get.await_count == 2
    assert not hasattr(redis, "sadd")


@pytest.mark.asyncio
async def test_other_users_cannot_use_search_session():
    redis = SimpleNamespace(get=AsyncMock(return_value=json.dumps({
        "user": 42, "urls": [song(1).url],
    })))
    with pytest.raises(SearchSessionError, match="другого"):
        await read_search(redis, "abc0123456789def", 7)


@pytest.mark.asyncio
async def test_expired_search_does_not_create_more_redis_keys():
    redis = SimpleNamespace(get=AsyncMock(return_value=None))
    with pytest.raises(SearchSessionError, match="30 минут"):
        await read_search(redis, "abc0123456789def", 42)


def test_keyboard_uses_individual_actions_no_batch_button():
    token = "abc0123456789def"
    songs = [song(i) for i in range(10)]
    page0 = search_keyboard(token, songs, states={0: "success", 1: "queued"})
    assert page0.inline_keyboard[0][0].text.startswith("✅")
    assert page0.inline_keyboard[1][0].text.startswith("⏳")
    callbacks = [
        button.callback_data for row in page0.inline_keyboard for button in row
    ]
    assert f"find:{token}:0" in callbacks
    assert f"pls:{token}:0" in callbacks
    assert f"stash:{token}:0" in callbacks
    assert not any(callback.startswith("findall:") for callback in callbacks)
    page1 = search_keyboard(token, songs, page=1)
    assert page1.inline_keyboard[0][0].callback_data == f"find:{token}:5"
    assert any(button.callback_data == f"searchpage:{token}:0"
               for row in page1.inline_keyboard for button in row)
    assert PAGE_SIZE == 5


def test_search_ui_has_complete_title_artist_duration_and_statuses():
    text = render_search(
        [song(1), song(2)], "lil peep", states={0: "success", 1: "queued"},
    )
    assert "ZVUK" in text
    assert "lil peep" in text
    assert "Song 1" in text
    assert "Artist" in text
    assert "3:00" in text
    assert "✅ 01" in text and "⏳ 02" in text


@pytest.mark.asyncio
async def test_clicking_an_already_downloaded_result_does_not_enqueue():
    from app.bot.handlers import select_search_result

    session = SimpleNamespace(results=(song(1),), query="One song",
                              get=lambda index: song(index + 1))
    callback = SimpleNamespace(
        data="find:abc0123456789def:0", from_user=SimpleNamespace(id=42),
        message=SimpleNamespace(chat=SimpleNamespace(id=42)),
        answer=AsyncMock(),
    )
    with patch("app.bot.handlers._search_callback_context",
               new=AsyncMock(return_value=session)):
        with patch("app.bot.handlers.dispatch_download",
                   new=AsyncMock(return_value="downloaded")) as dispatched:
            with patch("app.bot.handlers._refresh_search", new=AsyncMock()):
                await select_search_result(
                    callback, AsyncMock(), AsyncMock(), AsyncMock(),
                    SimpleNamespace(register=AsyncMock()),
                    AsyncMock(), SimpleNamespace(max_pending_per_user=5),
                )
    dispatched.assert_awaited_once()
    assert dispatched.await_args.kwargs["notify_rejection"] is False
    callback.answer.assert_awaited_once()
    assert callback.answer.await_args.kwargs["show_alert"] is True
