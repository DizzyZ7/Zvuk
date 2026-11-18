from types import SimpleNamespace

from aiogram.types import InlineKeyboardMarkup

from app.bot.menu import home_keyboard
from app.bot.playlists import playlist_keyboard, track_keyboard


def test_home_keyboard_has_six_actions():
    labels = [button.callback_data for row in home_keyboard().inline_keyboard for button in row]
    assert set(labels) == {
        "home:search", "home:recognize", "home:library",
        "home:playlists", "home:premium", "home:help",
    }


def test_playlists_keyboard_has_safe_callbacks():
    rows = playlist_keyboard([SimpleNamespace(id=4, name="Nice songs")])
    assert isinstance(rows, InlineKeyboardMarkup)
    assert rows.inline_keyboard[0][0].callback_data == "plshow:4"


def test_playlist_track_buttons_have_distinct_actions():
    rows = track_keyboard([SimpleNamespace(id=5, title="Song")])
    assert [x.callback_data for x in rows.inline_keyboard[0]] == [
        "plplay:5", "pldrop:5",
    ]



def test_choose_playlist_buttons_include_search_token_and_owner_scoped_target():
    from app.bot.playlists import destination_keyboard

    token = "abc0123456789def"
    playlist = SimpleNamespace(id=12, name="Favorites")
    buttons = destination_keyboard([playlist], origin=token, index=5)
    assert buttons.inline_keyboard[0][0].callback_data == f"plsave:{token}:5:12"
