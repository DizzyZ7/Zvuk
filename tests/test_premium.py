from unittest.mock import AsyncMock

import pytest

from app.services.premium import PremiumService, InvalidPayment


@pytest.mark.asyncio
async def test_checkout_rejects_non_stars_without_database():
    svc = PremiumService(AsyncMock())
    assert await svc.validate_checkout("premium:abc", 123, "USD", 100) is False


@pytest.mark.asyncio
async def test_create_order_validates_price():
    svc = PremiumService(AsyncMock())
    with pytest.raises(ValueError):
        await svc.create_order(1, 0)


def test_entitlement_days_is_configurable():
    svc = PremiumService(AsyncMock(), days=30)
    assert svc.days == 30


def test_invalid_payment_error():
    assert issubclass(InvalidPayment, ValueError)
