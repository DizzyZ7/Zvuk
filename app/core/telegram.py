from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from app.core.config import settings

def make_bot() -> Bot:
    session = AiohttpSession(
        api=TelegramAPIServer.from_base(settings.bot_api_url, is_local=True),
        timeout=1200,
    )
    return Bot(settings.bot_token.get_secret_value(), session=session)
