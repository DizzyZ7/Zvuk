import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.music_search import SearchResult
from app.services.search_sessions import (
    MAX_BATCH_PER_TAP, PAGE_SIZE, SEARCH_TTL_SECONDS, SearchSessionError,
    create_search, mark_selected, read_search, selected_indices,
)


def song(i: int) -> SearchResult:
    return SearchResult(
        title=f"Song {i}", artist="Artist",
        url=f"https://www.youtube.com/watch?v={i:011d}", duration=180,
    )


@pytest.mark.asyncio
async def test_search_persists_ten_tracks_without_consuming():
    redis = SimpleNamespace(set=AsyncMock(), get=AsyncMock())
    results = [song(i) for i in range(10)]
    token = await create_search(redis, 42, results)
    assert len(token) == 16
    key, payload = redis.set.await_args.args
    assert key == f"search:{token}"
    assert redis.set.await_args.kwargs["ex"] == SEARCH_TTL_SECONDS
    redis.get.return_value = payload
    first = await read_search(redis, token, 42)
    second = await read_search(redis, token, 42)
    assert len(first.results) == 10
    assert first.results == second.results
    assert redis.get.await_count == 2


@pytest.mark.asyncio
async def test_search_for_another_user_is_denied():
    redis = SimpleNamespace(get=AsyncMock(return_value=json.dumps({
        "user": 42, "urls": [song(1).url],
    })))
    with pytest.raises(SearchSessionError, match="другого"):
        await read_search(redis, "abc0123456789def", 7)


@pytest.mark.asyncio
async def test_expired_results_have_helpful_message():
    redis = SimpleNamespace(get=AsyncMock(return_value=None))
    with pytest.raises(SearchSessionError, match="30 минут"):
        await read_search(redis, "abc0123456789def", 42)


@pytest.mark.asyncio
async def test_selections_are_independent_of_search_payload():
    redis = SimpleNamespace(sadd=AsyncMock(), expire=AsyncMock(),
                            smembers=AsyncMock(return_value={"0", "3"}))
    await mark_selected(redis, "abc0123456789def", 3)
    assert await selected_indices(redis, "abc0123456789def") == {0, 3}
    assert redis.expire.await_args.args[1] == SEARCH_TTL_SECONDS


def test_batch_capacity_and_page_size_are_bounded():
    assert PAGE_SIZE == 5
    assert MAX_BATCH_PER_TAP == 3



def test_keyboard_pages_and_marks_retryable_previous_selection():
    from app.bot.keyboards import search_keyboard

    token = "abc0123456789def"
    songs = [song(i) for i in range(10)]
    page0 = search_keyboard(token, songs, selected={0})
    assert page0.inline_keyboard[0][0].text.startswith("🔁")
    assert page0.inline_keyboard[0][0].callback_data == f"find:{token}:0"
    assert page0.inline_keyboard[-1][0].callback_data == f"findall:{token}"
    page1 = search_keyboard(token, songs, page=1)
    assert page1.inline_keyboard[0][0].callback_data == f"find:{token}:5"
    assert any(btn.callback_data == f"searchpage:{token}:0"
               for row in page1.inline_keyboard for btn in row)


@pytest.mark.asyncio
async def test_batch_selection_keeps_session_after_three_items():
    from unittest.mock import patch
    from app.bot.handlers import select_search_batch

    session = SimpleNamespace(results=tuple(song(i) for i in range(10)))
    user = SimpleNamespace(id=42)
    cb = SimpleNamespace(
        data="findall:abc0123456789def",
        from_user=user,
        message=SimpleNamespace(chat=SimpleNamespace(id=42)),
        answer=AsyncMock(),
    )
    redis = SimpleNamespace()
    with patch("app.bot.handlers._search_callback_context",
               new=AsyncMock(return_value=session)):
        with patch("app.bot.handlers.selected_indices",
                   new=AsyncMock(return_value={0})):
            with patch("app.bot.handlers._submit_search_results",
                       new=AsyncMock(return_value=(3, 0))) as submit:
                with patch("app.bot.handlers._refresh_search_keyboard",
                           new=AsyncMock()):
                    await select_search_batch(
                        cb, SimpleNamespace(), redis, SimpleNamespace(),
                        SimpleNamespace(register=AsyncMock()),
                        SimpleNamespace(), SimpleNamespace(),
                    )
    assert submit.await_args.args[2] == [1, 2, 3]
    cb.answer.assert_awaited_once()
