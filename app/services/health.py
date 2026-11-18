"""Mobile-friendly checks of the running deployment for bot administrators."""
import asyncio
from dataclasses import dataclass

from aiogram import Bot
from redis.asyncio import Redis
from sqlalchemy import text

from app.services.repository import Repository


@dataclass(frozen=True)
class HealthStatus:
    telegram: bool
    postgres: bool
    redis: bool
    worker: bool

    def display(self) -> str:
        def icon(ok: bool) -> str:
            return "✅" if ok else "❌"
        return (
            "🧪 Проверка Zvuk\n\n"
            f"{icon(self.telegram)} Telegram Bot API\n"
            f"{icon(self.postgres)} PostgreSQL\n"
            f"{icon(self.redis)} Redis\n"
            f"{icon(self.worker)} Media worker\n\n"
            "Это проверка компонентов, а не тест реального скачивания."
        )


async def health_status(bot: Bot, redis: Redis, repo: Repository) -> HealthStatus:
    async def telegram_ok() -> bool:
        try:
            await asyncio.wait_for(bot.get_me(), timeout=5)
            return True
        except Exception:
            return False

    async def postgres_ok() -> bool:
        try:
            async with repo.factory() as session:
                await asyncio.wait_for(session.execute(text("SELECT 1")), timeout=5)
            return True
        except Exception:
            return False

    async def redis_ok() -> bool:
        try:
            return bool(await asyncio.wait_for(redis.ping(), timeout=5))
        except Exception:
            return False

    async def worker_ok() -> bool:
        try:
            async def exists() -> bool:
                async for _ in redis.scan_iter(match="zvuk:worker:alive:*", count=10):
                    return True
                return False
            return await asyncio.wait_for(exists(), timeout=5)
        except Exception:
            return False

    telegram, postgres, redis_alive, worker = await asyncio.gather(
        telegram_ok(), postgres_ok(), redis_ok(), worker_ok(),
    )
    return HealthStatus(telegram, postgres, redis_alive, worker)
