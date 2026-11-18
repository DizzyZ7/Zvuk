"""Ownership-safe personal playlists backed by PostgreSQL."""
import hashlib

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Playlist, PlaylistTrack
from app.services.urls import MediaURL


class PlaylistService:
    def __init__(self, factory: async_sessionmaker[AsyncSession]):
        self.factory = factory

    async def create(self, user_id: int, name: str) -> Playlist:
        name = " ".join(name.split())
        if not 1 <= len(name) <= 80:
            raise ValueError("Название должно содержать от 1 до 80 символов.")
        async with self.factory.begin() as session:
            count = await session.scalar(
                select(func.count()).select_from(Playlist).where(Playlist.user_id == user_id),
            )
            if (count or 0) >= 25:
                raise ValueError("Лимит: 25 плейлистов на пользователя.")
            item = Playlist(user_id=user_id, name=name)
            session.add(item)
            await session.flush()
            return item

    async def list(self, user_id: int) -> list[Playlist]:
        async with self.factory() as session:
            return list((await session.scalars(
                select(Playlist).where(Playlist.user_id == user_id)
                .order_by(Playlist.id.desc()).limit(25),
            )).all())

    async def get(self, user_id: int, playlist_id: int) -> Playlist | None:
        async with self.factory() as session:
            return await session.scalar(
                select(Playlist).where(
                    Playlist.id == playlist_id, Playlist.user_id == user_id,
                ),
            )

    async def add(
        self, user_id: int, playlist_id: int, media: MediaURL,
        *, title: str, artist: str = "",
    ) -> bool:
        digest = hashlib.sha256(media.url.encode()).hexdigest()
        async with self.factory.begin() as session:
            owner = await session.scalar(
                select(Playlist).where(
                    Playlist.id == playlist_id, Playlist.user_id == user_id,
                ).with_for_update(),
            )
            if owner is None:
                return False
            count = await session.scalar(
                select(func.count()).select_from(PlaylistTrack)
                .where(PlaylistTrack.playlist_id == playlist_id),
            )
            if (count or 0) >= 200:
                raise ValueError("В одном плейлисте может быть не более 200 треков.")
            statement = insert(PlaylistTrack).values(
                playlist_id=playlist_id, url_hash=digest,
                url=media.url, title=title.strip()[:255] or media.platform,
                artist=artist.strip()[:255],
            ).on_conflict_do_nothing(constraint="uq_playlist_track_hash")
            await session.execute(statement)
            return True

    async def tracks(self, user_id: int, playlist_id: int, *, limit: int = 20):
        if not 1 <= limit <= 50:
            raise ValueError("Invalid limit")
        async with self.factory() as session:
            return list((await session.scalars(
                select(PlaylistTrack).join(
                    Playlist, PlaylistTrack.playlist_id == Playlist.id,
                ).where(
                    Playlist.id == playlist_id, Playlist.user_id == user_id,
                ).order_by(PlaylistTrack.id).limit(limit),
            )).all())

    async def track(self, user_id: int, track_id: int) -> PlaylistTrack | None:
        async with self.factory() as session:
            return await session.scalar(
                select(PlaylistTrack).join(
                    Playlist, PlaylistTrack.playlist_id == Playlist.id,
                ).where(
                    PlaylistTrack.id == track_id, Playlist.user_id == user_id,
                ),
            )

    async def remove_track(self, user_id: int, track_id: int) -> bool:
        async with self.factory.begin() as session:
            result = await session.execute(
                delete(PlaylistTrack).where(
                    PlaylistTrack.id == track_id,
                    PlaylistTrack.playlist_id.in_(
                        select(Playlist.id).where(Playlist.user_id == user_id),
                    ),
                ).returning(PlaylistTrack.id),
            )
            return result.scalar_one_or_none() is not None

    async def delete(self, user_id: int, playlist_id: int) -> bool:
        async with self.factory.begin() as session:
            result = await session.execute(
                delete(Playlist).where(
                    Playlist.id == playlist_id, Playlist.user_id == user_id,
                ).returning(Playlist.id),
            )
            return result.scalar_one_or_none() is not None
