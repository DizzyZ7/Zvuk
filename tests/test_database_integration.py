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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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
