"""PostgreSQL-backed temporary state with atomic TTL and rate limits.

This replaces Redis for search/format buttons, temporary locks, and counters.
No separate process or Redis protocol server is required.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.entities import AppState


class StateStore:
    def __init__(self, factory: async_sessionmaker[AsyncSession]):
        self.factory = factory

    async def ping(self) -> bool:
        async with self.factory() as session:
            return bool(await session.scalar(select(1)))

    async def set(
        self, key: str, value: str | int, *, ex: int | None = None, nx: bool = False,
    ) -> bool:
        expires = (datetime.now(timezone.utc) + timedelta(seconds=ex)) if ex else None
        now = datetime.now(timezone.utc)
        async with self.factory.begin() as session:
            statement = insert(AppState).values(
                key=key, value=str(value), expires_at=expires,
            )
            if nx:
                statement = statement.on_conflict_do_update(
                    index_elements=[AppState.key],
                    set_={"value": str(value), "expires_at": expires},
                    where=AppState.expires_at <= now,
                )
            else:
                statement = statement.on_conflict_do_update(
                    index_elements=[AppState.key],
                    set_={"value": str(value), "expires_at": expires},
                )
            result = await session.execute(statement)
            return bool(result.rowcount)

    async def get(self, key: str) -> str | None:
        now = datetime.now(timezone.utc)
        async with self.factory() as session:
            return await session.scalar(
                select(AppState.value).where(
                    AppState.key == key,
                    or_(AppState.expires_at.is_(None), AppState.expires_at > now),
                )
            )

    async def delete(self, key: str) -> int:
        async with self.factory.begin() as session:
            return (await session.execute(delete(AppState).where(
                AppState.key == key,
            ))).rowcount

    async def exists(self, key: str) -> bool:
        return (await self.get(key)) is not None

    async def release_lock(self, key: str, token: str) -> bool:
        async with self.factory.begin() as session:
            result = await session.execute(
                delete(AppState).where(
                    AppState.key == key, AppState.value == token,
                )
            )
            return bool(result.rowcount)

    async def scan_iter(self, *, match: str, count: int = 10):
        # Only used by admin /health with a fixed trusted pattern.
        if match != "zvuk:worker:alive:*":
            raise ValueError("Unsupported state scan")
        async with self.factory() as session:
            values = (await session.scalars(
                select(AppState.key).where(
                    AppState.key.like("zvuk:worker:alive:%"),
                    AppState.expires_at > datetime.now(timezone.utc),
                ).limit(count)
            )).all()
        for value in values:
            yield value

    async def reserve_recognition(
        self, user_id: int, *, daily_limit: int, monthly_cap: int,
    ) -> int:
        """Atomic global cost ceiling + individual daily quota.

        Returns 0 on success, 1 if daily quota reached, 2 for monthly cap.
        """
        now = datetime.now(timezone.utc)
        daily_key = f"recognition:daily:{user_id}"
        monthly_key = f"recognition:month:{now:%Y-%m}"
        async with self.factory.begin() as session:
            # A global advisory transaction lock prevents two concurrent users
            # from overshooting the shared paid-API monthly cap.
            await session.execute(text("SELECT pg_advisory_xact_lock(-9478021)"))
            rows = (await session.scalars(
                select(AppState).where(
                    AppState.key.in_([daily_key, monthly_key]),
                )
            )).all()
            by_key = {r.key: r for r in rows}

            def current(key: str) -> int:
                item = by_key.get(key)
                if not item or (item.expires_at and item.expires_at <= now):
                    return 0
                return int(item.value)

            if current(daily_key) >= daily_limit:
                return 1
            if current(monthly_key) >= monthly_cap:
                return 2
            for key, ttl in ((daily_key, 86400), (monthly_key, 3456000)):
                expiry = now + timedelta(seconds=ttl)
                item = by_key.get(key)
                if item:
                    item.value = str(current(key) + 1)
                    if item.expires_at is None or item.expires_at <= now:
                        item.expires_at = expiry
                else:
                    session.add(AppState(
                        key=key, value="1", expires_at=expiry,
                    ))
        return 0

    async def prune_expired(self) -> int:
        async with self.factory.begin() as session:
            result = await session.execute(
                delete(AppState).where(
                    AppState.expires_at < datetime.now(timezone.utc),
                )
            )
            return int(result.rowcount)
