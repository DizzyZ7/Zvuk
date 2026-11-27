"""Run database integration tests against migrated PostgreSQL in GitHub Actions."""
import os
from uuid import uuid4

import pytest
import pytest_asyncio

from app.core.database import engine, session_factory
from app.models import User
from app.services.library import TrackLibrary
from app.services.premium import InvalidPayment, PremiumService
from app.services.repository import Repository
from app.services.urls import parse_media_url

@pytest_asyncio.fixture(scope="module", loop_scope="module", autouse=True)
async def dispose_db_pool():
    yield
    await engine.dispose()


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DB_TESTS") != "1",
    reason="Requires migrated PostgreSQL and RUN_DB_TESTS=1",
)


@pytest.mark.asyncio(loop_scope="module")
async def test_stars_checkout_payment_and_idempotent_grant():
    user_id = 10_000_000_001
    async with session_factory.begin() as session:
        session.add(User(id=user_id, username="integration_test_premium"))
    service = PremiumService(session_factory, days=30)
    payload = await service.create_order(user_id, 149)
    assert not await service.validate_checkout(payload, user_id, "USD", 149)
    assert not await service.validate_checkout(payload, user_id, "XTR", 150)
    assert await service.validate_checkout(payload, user_id, "XTR", 149)

    charge = "test_charge_" + uuid4().hex
    expiry, first = await service.complete(payload, user_id, "XTR", 149, charge)
    assert first
    assert await service.active_until(user_id) == expiry
    assert not await service.validate_checkout(payload, user_id, "XTR", 149)

    repeated_expiry, repeated = await service.complete(
        payload, user_id, "XTR", 149, charge,
    )
    assert repeated_expiry == expiry
    assert repeated is False

    with pytest.raises(InvalidPayment):
        await service.complete(payload, user_id, "XTR", 149, "different_charge_" + uuid4().hex)


@pytest.mark.asyncio(loop_scope="module")
async def test_library_isolated_by_owner_and_deduplicated():
    ids = [10_000_000_002, 10_000_000_003]
    async with session_factory.begin() as session:
        session.add_all(User(id=uid) for uid in ids)
    lib = TrackLibrary(session_factory)
    media = parse_media_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    await lib.save(ids[0], media, title="Test song")
    await lib.save(ids[0], media, title="Updated title")
    assert await lib.count(ids[0]) == 1
    tracks = await lib.list(ids[0])
    assert tracks[0].title == "Updated title"
    assert await lib.get(ids[1], tracks[0].id) is None
    assert not await lib.delete(ids[1], tracks[0].id)
    assert await lib.delete(ids[0], tracks[0].id)
    assert await lib.count(ids[0]) == 0


@pytest.mark.asyncio(loop_scope="module")
async def test_campaign_limit_and_deliveries():
    repo = Repository(session_factory, redis=None)  # No Redis calls in campaign methods.
    cid = await repo.add_campaign(
        label="Integration", caption="Example",
        target_url="https://example.org", impressions_limit=2,
    )
    campaign = await repo.select_campaign()
    assert campaign is not None and campaign.id == cid
    assert await repo.record_campaign_impression(cid)
    assert await repo.record_campaign_impression(cid)
    assert not await repo.record_campaign_impression(cid)
    assert await repo.select_campaign() is None
    assert await repo.set_campaign_enabled(cid, enabled=False)
    campaigns = await repo.list_campaigns()
    assert any(c.id == cid and c.impressions == 2 for c in campaigns)



@pytest.mark.asyncio(loop_scope="module")
async def test_playlists_are_private_and_track_urls_are_deduplicated():
    from app.services.playlists import PlaylistService

    ids = [10_000_000_004, 10_000_000_005]
    async with session_factory.begin() as session:
        session.add_all(User(id=uid) for uid in ids)
    playlists = PlaylistService(session_factory)
    created = await playlists.create(ids[0], "My favorites")
    track = parse_media_url("https://youtu.be/dQw4w9WgXcQ")
    assert await playlists.add(ids[0], created.id, track, title="Demo")
    assert await playlists.add(ids[0], created.id, track, title="Demo")
    assert len(await playlists.tracks(ids[0], created.id)) == 1
    assert await playlists.get(ids[1], created.id) is None
    assert not await playlists.add(ids[1], created.id, track, title="Stolen")
    assert not await playlists.tracks(ids[1], created.id)
    song = (await playlists.tracks(ids[0], created.id))[0]
    assert await playlists.track(ids[1], song.id) is None
    assert not await playlists.remove_track(ids[1], song.id)
    assert await playlists.remove_track(ids[0], song.id)
    assert await playlists.delete(ids[0], created.id)


@pytest.mark.asyncio(loop_scope="module")
async def test_cash_ledger_reports_only_actual_rub_entries():
    from app.services.cash_ledger import CashLedger

    ledger = CashLedger(session_factory)
    await ledger.add("income", 2000, "Advertising", "Test invoice")
    await ledger.add("expense", 850, "Hosting", "VPS")
    income, expenses, entries = await ledger.month()
    assert income == 2000
    assert expenses == 850
    assert {e.category for e in entries} == {"Hosting", "Advertising"}



@pytest.mark.asyncio(loop_scope="module")
async def test_download_reservation_skips_success_and_active_duplicates():
    from app.services.urls import cache_key

    uid = 10_000_000_006
    async with session_factory.begin() as session:
        session.add(User(id=uid))
    repo = Repository(session_factory, redis=None)
    media = parse_media_url("https://youtu.be/dQw4w9WgXcQ")
    key = cache_key(media, "audio")

    status, job = await repo.reserve_download(uid, media.url, key, "audio", 5)
    assert status == "reserved"
    assert job
    assert await repo.download_states(uid, [key]) == {key: "queued"}
    assert await repo.reserve_download(uid, media.url, key, "audio", 5) == (
        "pending", None,
    )
    await repo.update_download(job, "processing")
    assert await repo.reserve_download(uid, media.url, key, "audio", 5) == (
        "pending", None,
    )
    await repo.update_download(job, "success")
    assert await repo.download_states(uid, [key]) == {key: "success"}
    assert await repo.reserve_download(uid, media.url, key, "audio", 5) == (
        "downloaded", None,
    )
    # MP4 is a different output format and may be downloaded once separately.
    other_status, other_job = await repo.reserve_download(
        uid, media.url, cache_key(media, "video"), "video", 5,
    )
    assert other_status == "reserved" and other_job


@pytest.mark.asyncio(loop_scope="module")
async def test_failed_download_can_be_retried():
    from app.services.urls import cache_key

    uid = 10_000_000_007
    async with session_factory.begin() as session:
        session.add(User(id=uid))
    repo = Repository(session_factory, redis=None)
    media = parse_media_url("https://youtu.be/abcdefghijk")
    key = cache_key(media, "audio")
    status, job = await repo.reserve_download(uid, media.url, key, "audio", 5)
    assert status == "reserved"
    await repo.update_download(job, "failed", "temporary provider error")
    status, another = await repo.reserve_download(uid, media.url, key, "audio", 5)
    assert status == "reserved"
    assert another != job


@pytest.mark.asyncio(loop_scope="module")
async def test_five_quick_distinct_tracks_are_allowed_but_sixth_waits():
    import asyncio
    from app.services.urls import cache_key

    uid = 10_000_000_008
    async with session_factory.begin() as session:
        session.add(User(id=uid))
    repo = Repository(session_factory, redis=None)
    links = [
        parse_media_url(f"https://www.youtube.com/watch?v={i:011d}")
        for i in range(6)
    ]
    outcomes = await asyncio.gather(*[
        repo.reserve_download(uid, media.url, cache_key(media, "audio"), "audio", 5)
        for media in links
    ])
    assert sum(status == "reserved" for status, _ in outcomes) == 5
    assert sum(status == "limit" for status, _ in outcomes) == 1


@pytest.mark.asyncio(loop_scope="module")
async def test_simultaneous_duplicate_callbacks_reserve_only_one_job():
    import asyncio
    from app.services.urls import cache_key

    uid = 10_000_000_009
    async with session_factory.begin() as session:
        session.add(User(id=uid))
    repo = Repository(session_factory, redis=None)
    media = parse_media_url("https://youtu.be/abcdefghijk")
    key = cache_key(media, "audio")
    outcomes = await asyncio.gather(*[
        repo.reserve_download(uid, media.url, key, "audio", 5)
        for _ in range(6)
    ])
    assert sum(state == "reserved" for state, _ in outcomes) == 1
    assert sum(state == "pending" for state, _ in outcomes) == 5


@pytest.mark.asyncio(loop_scope="module")
async def test_one_users_success_does_not_block_another_users_first_file():
    from app.services.urls import cache_key

    uid = 10_000_000_010
    other = 10_000_000_011
    async with session_factory.begin() as session:
        session.add_all([User(id=uid), User(id=other)])
    repo = Repository(session_factory, redis=None)
    media = parse_media_url("https://youtu.be/abcdefghijk")
    key = cache_key(media, "audio")
    status, job = await repo.reserve_download(uid, media.url, key, "audio", 5)
    assert status == "reserved"
    await repo.update_download(job, "success")
    assert (await repo.reserve_download(other, media.url, key, "audio", 5))[0] == "reserved"



@pytest.mark.asyncio(loop_scope="module")
async def test_clip_one_reservation_and_two_independent_delivery_markers():
    from app.services.urls import cache_key

    uid = 10_000_000_012
    async with session_factory.begin() as session:
        session.add(User(id=uid))
    repo = Repository(session_factory, redis=None)
    media = parse_media_url(
        "https://www.instagram.com/reel/DgLOE34yzwp/?lqvp=tracking",
    )
    ck = cache_key(media, "clip")
    vk = cache_key(media, "video")
    ak = cache_key(media, "audio")
    status, jid = await repo.reserve_clip_download(
        uid, media.url, ck, vk, ak, 5,
    )
    assert status == "reserved" and jid
    assert await repo.reserve_clip_download(
        uid, media.url, ck, vk, ak, 5,
    ) == ("pending", None)

    await repo.update_download(jid, "processing")
    await repo.record_delivered_output(uid, media.url, vk, "video")
    assert await repo.download_states(uid, [vk, ak]) == {vk: "success"}
    await repo.update_download(jid, "failed", "MP3 conversion failure")

    # The video remains marked delivered, and the entire clip can be retried.
    status, retry_id = await repo.reserve_clip_download(
        uid, media.url, ck, vk, ak, 5,
    )
    assert status == "reserved" and retry_id != jid
    await repo.update_download(retry_id, "processing")
    await repo.record_delivered_output(uid, media.url, ak, "audio")
    assert await repo.download_states(uid, [vk, ak]) == {
        vk: "success", ak: "success",
    }
    await repo.update_download(retry_id, "success")
    assert await repo.reserve_clip_download(
        uid, media.url, ck, vk, ak, 5,
    ) == ("downloaded", None)


@pytest.mark.asyncio(loop_scope="module")
async def test_existing_video_and_audio_individually_prevent_clip_redelivery():
    from app.services.urls import cache_key

    uid = 10_000_000_013
    async with session_factory.begin() as session:
        session.add(User(id=uid))
    repo = Repository(session_factory, redis=None)
    media = parse_media_url("https://www.youtube.com/shorts/dQw4w9WgXcQ")
    vk, ak, ck = (cache_key(media, kind)
                  for kind in ("video", "audio", "clip"))
    await repo.record_delivered_output(uid, media.url, vk, "video")
    await repo.record_delivered_output(uid, media.url, ak, "audio")
    assert await repo.reserve_clip_download(
        uid, media.url, ck, vk, ak, 5,
    ) == ("downloaded", None)
