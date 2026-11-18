"""Personal, per-user collection of links and track metadata."""
import hashlib

from sqlalchemy import select, delete, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import SavedTrack
from app.services.urls import MediaURL


class TrackLibrary:
    def __init__(self, factory: async_sessionmaker[AsyncSession]):
        self.factory = factory

    async def save(
        self, user_id: int, media: MediaURL, *, title: str, artist: str = "",
    ) -> None:
        digest = hashlib.sha256(media.url.encode("utf-8")).hexdigest()
        async with self.factory.begin() as session:
            stmt = insert(SavedTrack).values(
                user_id=user_id, url_hash=digest, url=media.url,
                title=title.strip()[:255] or media.platform.title(),
                artist=artist.strip()[:255],
            ).on_conflict_do_update(
                constraint="uq_saved_user_hash",
                set_={"title": title.strip()[:255] or media.platform.title(),
                      "artist": artist.strip()[:255]},
            )
            await session.execute(stmt)

    async def list(self, user_id: int, *, limit: int = 10, offset: int = 0) -> list[SavedTrack]:
        if not 1 <= limit <= 50 or offset < 0:
            raise ValueError("Invalid pagination")
        async with self.factory() as session:
            return list((await session.scalars(
                select(SavedTrack).where(SavedTrack.user_id == user_id)
                .order_by(SavedTrack.created_at.desc(), SavedTrack.id.desc())
                .limit(limit).offset(offset),
            )).all())

    async def get(self, user_id: int, track_id: int) -> SavedTrack | None:
        async with self.factory() as session:
            return await session.scalar(
                select(SavedTrack).where(
                    SavedTrack.user_id == user_id, SavedTrack.id == track_id,
                )
            )

    async def delete(self, user_id: int, track_id: int) -> bool:
        async with self.factory.begin() as session:
            result = await session.execute(
                delete(SavedTrack)
                .where(SavedTrack.user_id == user_id, SavedTrack.id == track_id)
                .returning(SavedTrack.id)
            )
            return result.scalar_one_or_none() is not None

    async def count(self, user_id: int) -> int:
        async with self.factory() as session:
            return int(await session.scalar(select(func.count()).select_from(SavedTrack)
                                           .where(SavedTrack.user_id == user_id)) or 0)
