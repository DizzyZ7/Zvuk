from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import and_, delete, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
from app.models import (AdCampaign, AdPost, AppState, Broadcast, DeliveryReceipt, DownloadHistory, MediaCache,
                        PremiumGrant, PremiumPayment, SponsorChannel, User)
from app.core.state import StateStore

class Repository:
    def __init__(self, factory: async_sessionmaker[AsyncSession], state: StateStore | None = None):
        self.factory = factory
        self.state = state or StateStore(factory)

    async def touch_user(self, user_id: int, username: str | None) -> None:
        async with self.factory.begin() as session:
            stmt = insert(User).values(id=user_id, username=username, last_seen=func.now())
            stmt = stmt.on_conflict_do_update(
                index_elements=[User.id],
                set_={"username": username, "last_seen": func.now(), "is_blocked": False},
            )
            await session.execute(stmt)

    async def cache_get(self, key: str) -> str | None:
        async with self.factory() as session:
            item = await session.get(MediaCache, key)
            return item.file_id if item else None

    async def cache_put(self, key: str, file_id: str, kind: str) -> None:
        async with self.factory.begin() as session:
            stmt = insert(MediaCache).values(key=key, file_id=file_id, media_type=kind)
            stmt = stmt.on_conflict_do_update(
                index_elements=[MediaCache.key],
                set_={"file_id": file_id, "media_type": kind, "created_at": func.now()},
            )
            await session.execute(stmt)

    async def cache_drop(self, key: str) -> None:
        async with self.factory.begin() as session:
            await session.execute(delete(MediaCache).where(MediaCache.key == key))

    @staticmethod
    async def _notify(session: AsyncSession, event: str) -> None:
        # Commit delivers this notification *after* the durable row exists.
        await session.execute(
            text("SELECT pg_notify('zvuk_jobs', :event)"), {"event": event},
        )

    @staticmethod
    async def _receipt(session: AsyncSession, user_id: int, key: str) -> None:
        await session.execute(
            insert(DeliveryReceipt).values(
                user_id=user_id, cache_key=key,
            ).on_conflict_do_nothing(
                index_elements=[DeliveryReceipt.user_id, DeliveryReceipt.cache_key],
            )
        )

    async def new_download(self, user_id: int, url: str, key: str, kind: str) -> str:
        job_id = uuid4().hex
        async with self.factory.begin() as session:
            session.add(DownloadHistory(id=job_id, user_id=user_id, url=url,
                                        cache_key=key, kind=kind, status="queued"))
            await session.flush()
            await self._notify(session, "download")
        return job_id

    async def record_delivered_output(
        self, user_id: int, url: str, key: str, kind: str, *,
        cache_hit: bool = False,
    ) -> None:
        """Track clip outputs independently to avoid replay on partial retries."""
        async with self.factory.begin() as session:
            session.add(DownloadHistory(
                id=uuid4().hex, user_id=user_id, url=url,
                cache_key=key, kind=kind, status="success",
                cache_hit=cache_hit, finished_at=datetime.now(timezone.utc),
            ))
            await self._receipt(session, user_id, key)

    async def reserve_clip_download(
        self, user_id: int, url: str, key: str,
        video_key: str, audio_key: str, max_pending: int,
    ) -> tuple[str, str | None]:
        """Avoid a clip job if both outputs were already delivered separately."""
        async with self.factory.begin() as session:
            await session.execute(select(func.pg_advisory_xact_lock(user_id)))
            rows = (await session.execute(
                select(DownloadHistory.cache_key, DownloadHistory.status)
                .where(
                    DownloadHistory.user_id == user_id,
                    DownloadHistory.cache_key.in_([key, video_key, audio_key]),
                    DownloadHistory.status.in_(("success", "queued", "processing")),
                )
            )).all()
            delivered = (await session.scalars(
                select(DeliveryReceipt.cache_key).where(
                    DeliveryReceipt.user_id == user_id,
                    DeliveryReceipt.cache_key.in_([key, video_key, audio_key]),
                )
            )).all()
            states: dict[str, set[str]] = {key: {"success"} for key in delivered}
            for k, state in rows:
                states.setdefault(k, set()).add(state)
            if "success" in states.get(key, set()) or all(
                "success" in states.get(output, set())
                for output in (video_key, audio_key)
            ):
                return "downloaded", None
            if states.get(key, set()) & {"queued", "processing"}:
                return "pending", None
            active = await session.scalar(
                select(func.count()).select_from(DownloadHistory).where(
                    DownloadHistory.user_id == user_id,
                    DownloadHistory.status.in_(("queued", "processing")),
                )
            )
            if int(active or 0) >= max_pending:
                return "limit", None
            job_id = uuid4().hex
            session.add(DownloadHistory(
                id=job_id, user_id=user_id, url=url,
                cache_key=key, kind="clip", status="queued",
            ))
            await session.flush()
            await self._notify(session, "download")
            return "reserved", job_id

    async def reserve_download(
        self, user_id: int, url: str, key: str, kind: str, max_pending: int,
    ) -> tuple[str, str | None]:
        """Atomically reject a user's completed/active duplicate, or reserve a slot.

        A PostgreSQL advisory transaction lock per Telegram user serializes
        concurrent requests across processes, including different tracks.
        This replaces temporary Redis admission/selection locks.
        """
        async with self.factory.begin() as session:
            await session.execute(select(func.pg_advisory_xact_lock(user_id)))
            rows = (await session.scalars(
                select(DownloadHistory.status).where(
                    DownloadHistory.user_id == user_id,
                    DownloadHistory.cache_key == key,
                    DownloadHistory.status.in_(("success", "queued", "processing")),
                ),
            )).all()
            if "success" in rows or await session.get(
                DeliveryReceipt, (user_id, key),
            ) is not None:
                return "downloaded", None
            if "queued" in rows or "processing" in rows:
                return "pending", None
            active = await session.scalar(
                select(func.count()).select_from(DownloadHistory).where(
                    DownloadHistory.user_id == user_id,
                    DownloadHistory.status.in_(("queued", "processing")),
                ),
            )
            if int(active or 0) >= max_pending:
                return "limit", None
            job_id = uuid4().hex
            session.add(DownloadHistory(
                id=job_id, user_id=user_id, url=url, cache_key=key,
                kind=kind, status="queued",
            ))
            await session.flush()
            await self._notify(session, "download")
            return "reserved", job_id

    async def download_states(self, user_id: int, keys: list[str]) -> dict[str, str]:
        """One PostgreSQL query for statuses of the current search page."""
        if not keys:
            return {}
        if len(keys) > 20:
            raise ValueError("Too many status keys")
        priority = {"success": 3, "processing": 2, "queued": 1}
        async with self.factory() as session:
            rows = (await session.execute(
                select(DownloadHistory.cache_key, DownloadHistory.status).where(
                    DownloadHistory.user_id == user_id,
                    DownloadHistory.cache_key.in_(keys),
                    DownloadHistory.status.in_(tuple(priority)),
                ),
            )).all()
        async with self.factory() as session:
            receipts = (await session.scalars(
                select(DeliveryReceipt.cache_key).where(
                    DeliveryReceipt.user_id == user_id,
                    DeliveryReceipt.cache_key.in_(keys),
                ),
            )).all()
        result: dict[str, str] = {key: "success" for key in receipts}
        for key, status in rows:
            if priority[status] > priority.get(result.get(key, ""), 0):
                result[key] = status
        return result

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
            values["lease_until"] = None
        async with self.factory.begin() as session:
            row = await session.scalar(
                select(DownloadHistory).where(
                    DownloadHistory.id == job_id,
                ).with_for_update()
            )
            if row is None:
                return
            if status in ("success", "failed") and row.status == "success":
                return
            await session.execute(
                update(DownloadHistory).where(DownloadHistory.id == job_id)
                .values(**values)
            )
            if status == "success":
                await self._receipt(session, row.user_id, row.cache_key)

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
        async with self.factory() as session:
            ad = await session.get(AdPost, 1)
            return ad.text if ad and ad.enabled else ""

    async def set_ad(self, value: str) -> None:
        async with self.factory.begin() as session:
            stmt = insert(AdPost).values(id=1, text=value, enabled=bool(value))
            stmt = stmt.on_conflict_do_update(
                index_elements=[AdPost.id],
                set_={"text": value, "enabled": bool(value)},
            )
            await session.execute(stmt)

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
        async with self.factory() as session:
            downloads = await session.scalar(
                select(func.count()).select_from(DownloadHistory).where(
                    DownloadHistory.status.in_(("queued", "processing")),
                ),
            )
            broadcasts = await session.scalar(
                select(func.count()).select_from(Broadcast).where(
                    Broadcast.status.in_(("queued", "running")),
                ),
            )
            return int(downloads or 0), int(broadcasts or 0)

    async def premium_stats(self) -> tuple[int, int, int]:
        """Active subscriptions, completed payments and gross Stars (not fiat revenue)."""
        now = datetime.now(timezone.utc)
        async with self.factory() as session:
            active = await session.scalar(
                select(func.count()).select_from(PremiumGrant)
                .where(PremiumGrant.valid_until > now)
            )
            payments = await session.scalar(
                select(func.count()).select_from(PremiumPayment)
                .where(PremiumPayment.refunded.is_(False))
            )
            stars = await session.scalar(
                select(func.sum(PremiumPayment.stars))
                .where(PremiumPayment.refunded.is_(False))
            )
        return int(active or 0), int(payments or 0), int(stars or 0)

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
            await session.flush()
            await self._notify(session, "broadcast")
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

    async def claim_next_job(self, event: str) -> str | None:
        """FOR UPDATE SKIP LOCKED: no two workers can claim one job."""
        now = datetime.now(timezone.utc)
        lease_until = now + timedelta(minutes=8)
        async with self.factory.begin() as session:
            if event == "download":
                row = await session.scalar(
                    select(DownloadHistory)
                    .where(or_(
                        DownloadHistory.status == "queued",
                        and_(
                            DownloadHistory.status == "processing",
                            DownloadHistory.lease_until < now,
                        ),
                    ))
                    .order_by(DownloadHistory.created_at, DownloadHistory.id)
                    .limit(1).with_for_update(skip_locked=True)
                )
                if row:
                    row.status = "processing"
                    row.lease_until = lease_until
            elif event == "broadcast":
                row = await session.scalar(
                    select(Broadcast)
                    .where(or_(
                        Broadcast.status == "queued",
                        and_(
                            Broadcast.status == "running",
                            Broadcast.lease_until < now,
                        ),
                    ))
                    .order_by(Broadcast.created_at, Broadcast.id)
                    .limit(1).with_for_update(skip_locked=True)
                )
                if row:
                    row.status = "running"
                    row.lease_until = lease_until
            else:
                raise ValueError("Unknown queue")
            return row.id if row else None

    async def renew_job_lease(self, event: str, job_id: str) -> None:
        now = datetime.now(timezone.utc)
        async with self.factory.begin() as session:
            if event == "download":
                await session.execute(update(DownloadHistory).where(
                    DownloadHistory.id == job_id,
                    DownloadHistory.status == "processing",
                ).values(lease_until=now + timedelta(minutes=8)))
            elif event == "broadcast":
                await session.execute(update(Broadcast).where(
                    Broadcast.id == job_id,
                    Broadcast.status == "running",
                ).values(lease_until=now + timedelta(minutes=8)))

    async def cleanup_history(self, *, older_than_days: int = 30) -> int:
        """Keep tiny delivery receipts; purge verbose terminal job logs."""
        before = datetime.now(timezone.utc) - timedelta(days=older_than_days)
        async with self.factory.begin() as session:
            count = (await session.execute(delete(DownloadHistory).where(
                DownloadHistory.status.in_(("success", "failed")),
                DownloadHistory.finished_at < before,
            ))).rowcount
            return int(count)

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
