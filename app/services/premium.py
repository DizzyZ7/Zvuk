"""Telegram Stars Premium orders with transactional, idempotent entitlement delivery."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import PremiumGrant, PremiumOrder, PremiumPayment, User


class InvalidPayment(ValueError):
    pass


class PremiumService:
    def __init__(self, factory: async_sessionmaker[AsyncSession], days: int = 30):
        self.factory = factory
        self.days = days

    async def active_until(self, user_id: int) -> datetime | None:
        async with self.factory() as session:
            grant = await session.get(PremiumGrant, user_id)
            if grant and grant.valid_until > datetime.now(timezone.utc):
                return grant.valid_until
        return None

    async def create_order(self, user_id: int, stars: int) -> str:
        if not 1 <= stars <= 100_000:
            raise ValueError("Invalid Stars price")
        payload = f"premium:{uuid4().hex}"
        async with self.factory.begin() as session:
            session.add(PremiumOrder(payload=payload, user_id=user_id, stars=stars))
        return payload

    async def validate_checkout(
        self, payload: str, user_id: int, currency: str, amount: int,
    ) -> bool:
        if currency != "XTR" or not payload.startswith("premium:"):
            return False
        now = datetime.now(timezone.utc)
        async with self.factory() as session:
            order = await session.get(PremiumOrder, payload)
            return bool(
                order and order.user_id == user_id and order.stars == amount
                and order.paid_at is None
                and order.created_at >= now - timedelta(minutes=30)
            )

    async def complete(
        self, payload: str, user_id: int, currency: str, stars: int, charge_id: str,
    ) -> tuple[datetime, bool]:
        if currency != "XTR" or not charge_id or not 1 <= stars <= 100_000:
            raise InvalidPayment("Unexpected Telegram payment")
        now = datetime.now(timezone.utc)
        async with self.factory.begin() as session:
            # Serializes simultaneous orders for one user and entitlement updates.
            user = await session.scalar(
                select(User).where(User.id == user_id).with_for_update()
            )
            if user is None:
                raise InvalidPayment("Unknown paying user")
            order = await session.scalar(
                select(PremiumOrder)
                .where(PremiumOrder.payload == payload).with_for_update()
            )
            if order is None or order.user_id != user_id or order.stars != stars:
                raise InvalidPayment("Invalid payment payload or amount")
            payment = await session.get(PremiumPayment, charge_id)
            if payment:
                if payment.order_payload != payload:
                    raise InvalidPayment("Charge ID collision")
                grant = await session.get(PremiumGrant, user_id)
                if grant is None:
                    raise InvalidPayment("Payment/entitlement mismatch")
                return grant.valid_until, False
            if order.paid_at is not None:
                raise InvalidPayment("Order was already paid using a different charge")
            grant = await session.get(PremiumGrant, user_id)
            base = max(now, grant.valid_until) if grant is not None else now
            expiry = base + timedelta(days=self.days)
            if grant is None:
                session.add(PremiumGrant(user_id=user_id, valid_until=expiry))
            else:
                grant.valid_until = expiry
            session.add(PremiumPayment(
                charge_id=charge_id, order_payload=payload,
                user_id=user_id, stars=stars,
            ))
            order.paid_at = now
        return expiry, True
