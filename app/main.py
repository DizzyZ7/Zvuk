import asyncio
import logging

from aiogram import Dispatcher
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommand
from aiogram.fsm.storage.redis import RedisStorage
from app.bot import admin, campaigns, economics, handlers, legal, library, menu, playlists, premium, recognition
from app.bot.middlewares import SponsorMiddleware, ThrottleMiddleware
from app.core.config import settings
from app.core.database import engine, session_factory
from app.core.redis import make_redis
from app.core.telegram import make_bot
from app.services.ad_manager import AdManager
from app.services.library import TrackLibrary
from app.services.music_search import MusicSearch
from app.services.playlists import PlaylistService
from app.services.cash_ledger import CashLedger
from app.services.premium import PremiumService
from app.services.repository import Repository
from app.services.user_service import UserService

async def main() -> None:
    logging.basicConfig(level=settings.log_level.upper(),
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    redis = make_redis()
    storage = RedisStorage(redis=redis)
    repo = Repository(session_factory, redis)
    bot = make_bot()
    dp = Dispatcher(storage=storage)
    dp.include_router(admin.router)
    dp.include_router(campaigns.router)
    dp.include_router(economics.router)
    dp.include_router(premium.router)
    dp.include_router(legal.router)
    dp.include_router(library.router)
    dp.include_router(recognition.router)
    dp.include_router(playlists.router)
    dp.include_router(menu.router)
    dp.include_router(handlers.router)
    # Rate limiter runs before subscription check.
    dp.message.middleware(ThrottleMiddleware())
    dp.callback_query.middleware(ThrottleMiddleware())
    dp.message.middleware(SponsorMiddleware())
    dp.callback_query.middleware(SponsorMiddleware())
    try:
        await redis.ping()
        await bot.delete_webhook(drop_pending_updates=False)
        try:
            await bot.set_my_commands([
                BotCommand(command="start", description="Открыть Zvuk"),
                BotCommand(command="menu", description="Главное меню"),
                BotCommand(command="library", description="Избранные треки"),
                BotCommand(command="playlists", description="Мои плейлисты"),
                BotCommand(command="playlist", description="Создать плейлист или добавить песню"),
                BotCommand(command="fragment", description="Поиск песни по фразе"),
                BotCommand(command="premium", description="Статус и возможности Premium"),
                BotCommand(command="help", description="Как пользоваться ботом"),
            ])
        except TelegramAPIError:
            logging.getLogger(__name__).warning("Cannot update Telegram command menu")
        await dp.start_polling(
            bot, settings=settings, redis=redis, repo=repo,
            ads=AdManager(repo), users=UserService(repo), music_search=MusicSearch(),
            library=TrackLibrary(session_factory),
            playlists=PlaylistService(session_factory),
            ledger=CashLedger(session_factory),
            premium=PremiumService(session_factory, days=settings.premium_days),
            handle_signals=True,
        )
    finally:
        await dp.storage.close()
        await bot.session.close()
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
