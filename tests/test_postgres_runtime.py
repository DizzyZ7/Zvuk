"""PostgreSQL is the only required state and job queue backend."""
import asyncio
import os
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.core.database import engine, session_factory
from app.core.fsm import PostgresFSMStorage
from app.core.state import StateStore
from app.models import AppState, DeliveryReceipt, DownloadHistory, User
from app.services.queue import asyncpg_dsn, listen_for_jobs
from app.services.repository import Repository
from app.services.urls import cache_key, parse_media_url

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DB_TESTS") != "1",
    reason="Requires migrated PostgreSQL and RUN_DB_TESTS=1",
)


@pytest_asyncio.fixture(scope="module", loop_scope="module", autouse=True)
async def close_pool():
    yield
    await engine.dispose()


@pytest.mark.asyncio(loop_scope="module")
async def test_atomic_ttl_state_and_token_checked_release():
    state = StateStore(session_factory)
    key = "test:state:" + uuid4().hex
    assert await state.set(key, "owner-1", nx=True, ex=100)
    assert await state.get(key) == "owner-1"
    assert not await state.set(key, "owner-2", nx=True, ex=100)
    assert not await state.release_lock(key, "owner-2")
    assert await state.release_lock(key, "owner-1")
    assert await state.get(key) is None
    assert await state.set(key, "new", nx=True, ex=100)
    async with session_factory.begin() as session:
        from datetime import datetime, timedelta, timezone
        obj = await session.get(AppState, key)
        obj.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert await state.set(key, "renewed", nx=True, ex=100)
    assert await state.get(key) == "renewed"
    await state.delete(key)


@pytest.mark.asyncio(loop_scope="module")
async def test_global_recognition_quota_is_atomic():
    state = StateStore(session_factory)
    # Use an existing monthly counter's value temporarily; restore it after.
    from datetime import datetime, timezone
    monthly = f"recognition:month:{datetime.now(timezone.utc):%Y-%m}"
    daily = "recognition:daily:10000000014"
    async with session_factory.begin() as session:
        before = await session.get(AppState, monthly)
        snapshot = (
            (before.value, before.expires_at) if before is not None else None
        )
        if before:
            await session.delete(before)
    try:
        assert await state.reserve_recognition(
            10000000014, daily_limit=3, monthly_cap=2,
        ) == 0
        assert await state.reserve_recognition(
            10000000014, daily_limit=3, monthly_cap=2,
        ) == 0
        assert await state.reserve_recognition(
            10000000015, daily_limit=3, monthly_cap=2,
        ) == 2
    finally:
        async with session_factory.begin() as session:
            obj = await session.get(AppState, monthly)
            if obj:
                await session.delete(obj)
            if snapshot:
                session.add(AppState(key=monthly, value=snapshot[0],
                                     expires_at=snapshot[1]))
            await session.execute(delete(AppState).where(AppState.key == daily))


@pytest.mark.asyncio(loop_scope="module")
async def test_notifier_wakes_worker_only_after_durable_job_commit():
    state = StateStore(session_factory)
    repo = Repository(session_factory, state)
    uid = 10000000016
    async with session_factory.begin() as session:
        session.add(User(id=uid))
    media = parse_media_url("https://youtu.be/abcdefghijk")
    key = cache_key(media, "audio")
    wake = asyncio.Event()
    assert asyncpg_dsn().startswith("postgresql://")
    async with listen_for_jobs(wake):
        status, job_id = await repo.reserve_download(uid, media.url, key, "audio", 5)
        assert status == "reserved"
        await asyncio.wait_for(wake.wait(), timeout=5)
    # Other integration tests may have left queued rows; SKIP LOCKED is FIFO.
    claimed_id = None
    for _ in range(50):
        claimed_id = await repo.claim_next_job("download")
        if claimed_id == job_id:
            break
    assert claimed_id == job_id
    claimed = await repo.download(job_id)
    assert claimed.status == "processing"
    assert claimed.lease_until is not None
    await repo.update_download(job_id, "success")
    assert await repo.claim_next_job("download") != job_id
    assert await repo.download_states(uid, [key]) == {key: "success"}


@pytest.mark.asyncio(loop_scope="module")
async def test_receipt_survives_removal_of_verbose_download_history():
    repo = Repository(session_factory)
    uid = 10000000017
    async with session_factory.begin() as session:
        session.add(User(id=uid))
    media = parse_media_url("https://youtu.be/abcdefghijk")
    key = cache_key(media, "audio")
    status, job_id = await repo.reserve_download(uid, media.url, key, "audio", 5)
    assert status == "reserved"
    await repo.update_download(job_id, "success")
    async with session_factory.begin() as session:
        await session.execute(
            delete(DownloadHistory).where(DownloadHistory.id == job_id)
        )
    async with session_factory() as session:
        assert await session.get(DeliveryReceipt, (uid, key)) is not None
    assert await repo.reserve_download(uid, media.url, key, "audio", 5) == (
        "downloaded", None,
    )


@pytest.mark.asyncio(loop_scope="module")
async def test_fsm_persists_state_and_data_across_storage_instances():
    from aiogram.fsm.storage.base import StorageKey
    key = StorageKey(bot_id=12345, chat_id=10000000018, user_id=10000000018)
    s1 = PostgresFSMStorage(StateStore(session_factory))
    await s1.set_state(key, "AdminState:editing")
    await s1.set_data(key, {"source_id": 77})
    s2 = PostgresFSMStorage(StateStore(session_factory))
    assert await s2.get_state(key) == "AdminState:editing"
    assert await s2.get_data(key) == {"source_id": 77}
    await s2.set_state(key, None)
    await s2.set_data(key, {})
    assert await s1.get_state(key) is None
    assert await s1.get_data(key) == {}



@pytest.mark.asyncio(loop_scope="module")
async def test_postgres_advisory_media_lock_serializes_and_auto_releases():
    """Concurrent uploads wait for the same media lock, then reuse the cache."""
    store = StateStore(session_factory)
    lock = "media-lock:integration:" + uuid4().hex
    first_acquired = asyncio.Event()
    release_first = asyncio.Event()
    second_acquired = asyncio.Event()

    async def first():
        async with store.media_lock(lock):
            first_acquired.set()
            await release_first.wait()

    async def second():
        await first_acquired.wait()
        async with store.media_lock(lock):
            second_acquired.set()

    t1 = asyncio.create_task(first())
    t2 = asyncio.create_task(second())
    try:
        await asyncio.wait_for(first_acquired.wait(), 3)
        await asyncio.sleep(0.1)
        assert not second_acquired.is_set()
        release_first.set()
        await asyncio.wait_for(second_acquired.wait(), 3)
    finally:
        release_first.set()
        await asyncio.gather(t1, t2)
