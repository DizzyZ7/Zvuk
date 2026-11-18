import asyncio
import logging

from aiogram import Dispatcher
from aiogram.fsm.storage.redis import RedisStorage
from app.bot import admin, handlers, library, premium
from app.bot.middlewares import SponsorMiddleware, ThrottleMiddleware
from app.core.config import settings
from app.core.database import engine, session_factory
from app.core.redis import make_redis
from app.core.telegram import make_bot
from app.services.ad_manager import AdManager
from app.services.library import TrackLibrary
from app.services.music_search import MusicSearch
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
    dp.include_router(premium.router)
    dp.include_router(library.router)
    dp.include_router(handlers.router)
    # Rate limiter runs before subscription check.
    dp.message.middleware(ThrottleMiddleware())
    dp.callback_query.middleware(ThrottleMiddleware())
    dp.message.middleware(SponsorMiddleware())
    dp.callback_query.middleware(SponsorMiddleware())
    try:
        await redis.ping()
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(
            bot, settings=settings, redis=redis, repo=repo,
            ads=AdManager(repo), users=UserService(repo), music_search=MusicSearch(),
            library=TrackLibrary(session_factory),
            premium=PremiumService(session_factory, days=settings.premium_days),
            handle_signals=True,
        )
    finally:
        await dp.storage.close()
        await bot.session.close()
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
