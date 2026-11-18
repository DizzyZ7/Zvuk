"""Advertiser captions and Premium-free delivery; counts only successful sends."""
from dataclasses import dataclass
import logging

from sqlalchemy.exc import SQLAlchemyError

from app.services.premium import PremiumService
from app.services.repository import Repository


@dataclass(frozen=True)
class AdPlacement:
    caption: str | None
    campaign_id: int | None = None


log = logging.getLogger(__name__)


class AdManager:
    def __init__(self, repository: Repository):
        self.repository = repository
        self.premium = PremiumService(repository.factory)

    async def placement(self, user_id: int) -> AdPlacement:
        if await self.premium.active_until(user_id):
            return AdPlacement(caption=None)
        campaign = await self.repository.select_campaign()
        if campaign is not None:
            text = f"Реклама: {campaign.caption}\n{campaign.target_url}"
            return AdPlacement(caption=text[:1024], campaign_id=campaign.id)
        text = (await self.repository.ad_text()).strip()
        return AdPlacement(caption=text[:1024] if text else None)

    async def delivered(self, placement: AdPlacement) -> None:
        if placement.campaign_id is not None:
            try:
                await self.repository.record_campaign_impression(placement.campaign_id)
            except SQLAlchemyError:
                # The user already received the file. Never repeat delivery
                # just because the advertising analytics service is unavailable.
                log.exception("Impression accounting failed campaign=%s", placement.campaign_id)

    async def caption(self, user_id: int | None = None) -> str | None:
        # Kept for code that displays the legacy caption in the admin interface.
        if user_id is None:
            text = (await self.repository.ad_text()).strip()
            return text[:1024] if text else None
        return (await self.placement(user_id)).caption
