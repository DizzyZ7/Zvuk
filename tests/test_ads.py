from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.exc import OperationalError

from app.services.ad_manager import AdManager, AdPlacement
from app.services.premium import PremiumService


@pytest.mark.asyncio
async def test_premium_has_no_advertising():
    repo = SimpleNamespace(
        factory=object(), select_campaign=AsyncMock(), ad_text=AsyncMock(),
    )
    mgr = AdManager(repo)
    with patch.object(PremiumService, "active_until", new=AsyncMock(
        return_value=datetime.now(timezone.utc) + timedelta(days=1),
    )):
        placement = await mgr.placement(5)
    assert placement == AdPlacement(caption=None)
    repo.select_campaign.assert_not_awaited()
    repo.ad_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_free_user_uses_campaign_with_text_and_url():
    campaign = SimpleNamespace(
        id=3, caption="Поддержите наш проект", target_url="https://example.com",
    )
    repo = SimpleNamespace(factory=object(), select_campaign=AsyncMock(return_value=campaign))
    mgr = AdManager(repo)
    with patch.object(PremiumService, "active_until", new=AsyncMock(return_value=None)):
        placement = await mgr.placement(5)
    assert placement.campaign_id == 3
    assert placement.caption == "Реклама: Поддержите наш проект\nhttps://example.com"


@pytest.mark.asyncio
async def test_fallback_legacy_ad_and_untracked_impressions():
    repo = SimpleNamespace(
        factory=object(), select_campaign=AsyncMock(return_value=None),
        ad_text=AsyncMock(return_value="Старая реклама"),
    )
    mgr = AdManager(repo)
    with patch.object(PremiumService, "active_until", new=AsyncMock(return_value=None)):
        placement = await mgr.placement(5)
    assert placement == AdPlacement(caption="Старая реклама")
    await mgr.delivered(placement)


@pytest.mark.asyncio
async def test_failed_impression_accounting_does_not_duplicate_media():
    repo = SimpleNamespace(
        factory=object(),
        record_campaign_impression=AsyncMock(side_effect=OperationalError(
            "UPDATE", {}, Exception("connection failure"),
        )),
    )
    mgr = AdManager(repo)
    await mgr.delivered(AdPlacement("Реклама", campaign_id=4))
    repo.record_campaign_impression.assert_awaited_once_with(4)
