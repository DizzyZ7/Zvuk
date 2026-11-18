from datetime import datetime, timedelta, timezone
from uuid import uuid4

from redis.asyncio import Redis
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
from app.models import AdCampaign, AdPost, Broadcast, DownloadHistory, MediaCache, SponsorChannel, User
from app.services.queue import BROADCAST_STREAM, DOWNLOAD_STREAM

class Repository:
    def __init__(self, factory: async_sessionmaker[AsyncSession], redis: Redis):
        self.factory = factory
        self.redis = redis

    async def touch_user(self, user_id: int, username: str | None) -> None:
        async with self.factory.begin() as session:
            stmt = insert(User).values(id=user_id, username=username, last_seen=func.now())
            stmt = stmt.on_conflict_do_update(
                index_elements=[User.id],
                set_={"username": username, "last_seen": func.now(), "is_blocked": False},
            )
            await session.execute(stmt)

    async def cache_get(self, key: str) -> str | None:
        value = await self.redis.get(f"media:{key}")
        if value:
            return value
        async with self.factory() as session:
            item = await session.get(MediaCache, key)
            if item:
                await self.redis.set(f"media:{key}", item.file_id, ex=604800)
                return item.file_id
        return None

    async def cache_put(self, key: str, file_id: str, kind: str) -> None:
        async with self.factory.begin() as session:
            stmt = insert(MediaCache).values(key=key, file_id=file_id, media_type=kind)
            stmt = stmt.on_conflict_do_update(
                index_elements=[MediaCache.key],
                set_={"file_id": file_id, "media_type": kind, "created_at": func.now()},
            )
            await session.execute(stmt)
        await self.redis.set(f"media:{key}", file_id, ex=604800)

    async def cache_drop(self, key: str) -> None:
        async with self.factory.begin() as session:
            item = await session.get(MediaCache, key)
            if item:
                await session.delete(item)
        await self.redis.delete(f"media:{key}")

    async def new_download(self, user_id: int, url: str, key: str, kind: str) -> str:
        job_id = uuid4().hex
        async with self.factory.begin() as session:
            session.add(DownloadHistory(id=job_id, user_id=user_id, url=url,
                                        cache_key=key, kind=kind, status="queued"))
        return job_id

    async def pending_downloads(self, user_id: int) -> int:
        async with self.factory() as session:
            count = await session.scalar(
                select(func.count()).select_from(DownloadHistory).where(
                    DownloadHistory.user_id == user_id,
                    DownloadHistory.status.in_(("queued", "processing")),
                )
            )
            return int(count or 0)

    async def download(self, job_id: str) -> DownloadHistory | None:
        async with self.factory() as session:
            return await session.get(DownloadHistory, job_id)

    async def update_download(
        self, job_id: str, status: str, error: str | None = None, cache_hit: bool = False,
    ) -> None:
        values = {"status": status, "error": error[:1500] if error else None,
                  "cache_hit": cache_hit}
        if status in ("success", "failed"):
            values["finished_at"] = datetime.now(timezone.utc)
        async with self.factory.begin() as session:
            await session.execute(
                update(DownloadHistory).where(DownloadHistory.id == job_id).values(**values)
            )

    async def record_download_retry(self, job_id: str) -> int:
        async with self.factory.begin() as session:
            result = await session.execute(
                update(DownloadHistory)
                .where(DownloadHistory.id == job_id)
                .values(retry_count=DownloadHistory.retry_count + 1)
                .returning(DownloadHistory.retry_count)
            )
            value = result.scalar_one_or_none()
            if value is None:
                raise LookupError("Download job missing while retrying")
            return int(value)

    async def sponsors(self) -> list[SponsorChannel]:
        async with self.factory() as session:
            return list((await session.scalars(
                select(SponsorChannel).where(SponsorChannel.enabled.is_(True))
                .order_by(SponsorChannel.id)
            )).all())

    async def sponsor_add(self, chat_id: int, title: str, join_url: str) -> None:
        async with self.factory.begin() as session:
            stmt = insert(SponsorChannel).values(chat_id=chat_id, title=title, join_url=join_url)
            stmt = stmt.on_conflict_do_update(
                index_elements=[SponsorChannel.chat_id],
                set_={"title": title, "join_url": join_url, "enabled": True},
            )
            await session.execute(stmt)

    async def sponsor_remove(self, row_id: int) -> None:
        async with self.factory.begin() as session:
            row = await session.get(SponsorChannel, row_id)
            if row:
                await session.delete(row)

    async def ad_text(self) -> str:
        cached = await self.redis.get("active_ad")
        if cached is not None:
            return cached
        async with self.factory() as session:
            ad = await session.get(AdPost, 1)
            text = ad.text if ad and ad.enabled else ""
        await self.redis.set("active_ad", text, ex=60)
        return text

    async def set_ad(self, text: str) -> None:
        async with self.factory.begin() as session:
            stmt = insert(AdPost).values(id=1, text=text, enabled=bool(text))
            stmt = stmt.on_conflict_do_update(
                index_elements=[AdPost.id], set_={"text": text, "enabled": bool(text)},
            )
            await session.execute(stmt)
        await self.redis.delete("active_ad")

    async def add_campaign(
        self, *, label: str, caption: str, target_url: str,
        impressions_limit: int | None,
    ) -> int:
        async with self.factory.begin() as session:
            campaign = AdCampaign(
                label=label, caption=caption, target_url=target_url,
                impressions_limit=impressions_limit, enabled=True,
            )
            session.add(campaign)
            await session.flush()
            return campaign.id

    async def list_campaigns(self) -> list[AdCampaign]:
        async with self.factory() as session:
            return list((await session.scalars(
                select(AdCampaign).order_by(AdCampaign.id.desc()).limit(100)
            )).all())

    async def set_campaign_enabled(self, campaign_id: int, *, enabled: bool) -> bool:
        async with self.factory.begin() as session:
            result = await session.execute(
                update(AdCampaign).where(AdCampaign.id == campaign_id)
                .values(enabled=enabled).returning(AdCampaign.id)
            )
            return result.scalar_one_or_none() is not None

    async def select_campaign(self) -> AdCampaign | None:
        async with self.factory() as session:
            return await session.scalar(
                select(AdCampaign)
                .where(
                    AdCampaign.enabled.is_(True),
                    (AdCampaign.impressions_limit.is_(None) |
                     (AdCampaign.impressions < AdCampaign.impressions_limit)),
                )
                .order_by(AdCampaign.impressions, AdCampaign.id)
                .limit(1)
            )

    async def record_campaign_impression(self, campaign_id: int) -> bool:
        # Recording happens only after send_audio / send_video returns successfully.
        # This is best-effort accounting; an outage between send and commit may
        # undercount. The conditional update limits acknowledged impressions.
        async with self.factory.begin() as session:
            result = await session.execute(
                update(AdCampaign)
                .where(
                    AdCampaign.id == campaign_id,
                    (AdCampaign.impressions_limit.is_(None) |
                     (AdCampaign.impressions < AdCampaign.impressions_limit)),
                )
                .values(impressions=AdCampaign.impressions + 1)
                .returning(AdCampaign.id)
            )
            return result.scalar_one_or_none() is not None

    async def queue_depths(self) -> tuple[int, int]:
        """Approximate active and queued events; ACKed events are deleted from streams."""
        downloads = await self.redis.xlen(DOWNLOAD_STREAM)
        broadcasts = await self.redis.xlen(BROADCAST_STREAM)
        return int(downloads), int(broadcasts)

    async def stats(self) -> tuple[int, int, int, int]:
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        async with self.factory() as session:
            users = await session.scalar(select(func.count()).select_from(User))
            active = await session.scalar(
                select(func.count()).select_from(User).where(User.last_seen >= since)
            )
            downloads = await session.scalar(select(func.count()).select_from(DownloadHistory)
                                             .where(DownloadHistory.status == "success"))
            cached = await session.scalar(select(func.count()).select_from(DownloadHistory)
                                          .where(DownloadHistory.cache_hit.is_(True)))
        return int(users or 0), int(active or 0), int(downloads or 0), int(cached or 0)

    async def new_broadcast(
        self, admin_id: int, source_message_id: int, progress_message_id: int,
    ) -> str:
        job_id = uuid4().hex
        async with self.factory.begin() as session:
            total = int((await session.scalar(select(func.count()).select_from(User)
                                               .where(User.is_blocked.is_(False)))) or 0)
            session.add(Broadcast(id=job_id, admin_id=admin_id, source_chat_id=admin_id,
                                  source_message_id=source_message_id,
                                  progress_message_id=progress_message_id,
                                  total=total, status="queued"))
        return job_id

    async def broadcast_active(self) -> bool:
        async with self.factory() as session:
            active = await session.scalar(select(Broadcast.id).where(
                Broadcast.status.in_(("queued", "running"))
            ).limit(1))
            return active is not None

    async def cancel_broadcast(self, job_id: str, admin_id: int) -> bool:
        async with self.factory.begin() as session:
            result = await session.execute(
                update(Broadcast)
                .where(Broadcast.id == job_id, Broadcast.admin_id == admin_id,
                       Broadcast.status.in_(("queued", "running")))
                .values(status="cancelled")
                .returning(Broadcast.id)
            )
            return result.scalar_one_or_none() is not None

    async def get_broadcast(self, job_id: str) -> Broadcast | None:
        async with self.factory() as session:
            return await session.get(Broadcast, job_id)

    async def broadcast_progress(
        self, job_id: str, processed: int, failed: int, last_user_id: int, status: str,
    ) -> None:
        async with self.factory.begin() as session:
            await session.execute(
                update(Broadcast)
                .where(Broadcast.id == job_id, Broadcast.status.not_in_(("cancelled", "failed")))
                .values(processed=processed, failed=failed, last_user_id=last_user_id, status=status)
            )

    async def users_after(
        self, after: int, limit: int = 100, *, created_before: datetime | None = None,
    ) -> list[int]:
        async with self.factory() as session:
            query = select(User.id).where(
                User.id > after, User.is_blocked.is_(False),
            )
            if created_before is not None:
                query = query.where(User.created_at <= created_before)
            return list((await session.scalars(query.order_by(User.id).limit(limit))).all())

    async def user_block(self, user_id: int) -> None:
        async with self.factory.begin() as session:
            await session.execute(update(User).where(User.id == user_id)
                                  .values(is_blocked=True))
