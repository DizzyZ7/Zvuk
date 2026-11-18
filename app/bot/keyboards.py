from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from app.models import SponsorChannel

def format_keyboard(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🎵 Аудио MP3", callback_data=f"fmt:{token}:audio"),
        InlineKeyboardButton(text="🎬 Видео MP4", callback_data=f"fmt:{token}:video"),
    ]])

def subscribe_keyboard(channels: list[SponsorChannel]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"📢 {channel.title[:40]}", url=channel.join_url)]
            for channel in channels]
    rows.append([InlineKeyboardButton(text="✅ Проверить подписку", callback_data="sub:check")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="adm:stats")],
        [InlineKeyboardButton(text="📢 Спонсорские каналы", callback_data="adm:channels")],
        [InlineKeyboardButton(text="📝 Рекламная подпись", callback_data="adm:ads")],
        [InlineKeyboardButton(text="📨 Рассылка", callback_data="adm:broadcast")],
    ])
