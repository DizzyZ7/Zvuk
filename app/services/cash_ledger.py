"""Record realized cash receipts and expenses separately from Stars."""
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import CashEntry


class CashLedger:
    def __init__(self, factory: async_sessionmaker[AsyncSession]):
        self.factory = factory

    async def add(self, kind: str, amount_rub: int, category: str, note: str = "") -> int:
        if kind not in {"income", "expense"}:
            raise ValueError("Unsupported cash flow type")
        if not 1 <= amount_rub <= 100_000_000:
            raise ValueError("Сумма должна быть целым числом рублей от 1 до 100 млн.")
        category = " ".join(category.split())[:80]
        if not category:
            raise ValueError("Укажите категорию.")
        async with self.factory.begin() as session:
            entry = CashEntry(
                kind=kind, amount_rub=amount_rub, category=category,
                note=note.strip()[:255],
            )
            session.add(entry)
            await session.flush()
            return entry.id

    async def month(self, when: datetime | None = None):
        when = when or datetime.now(timezone.utc)
        start = datetime(when.year, when.month, 1, tzinfo=timezone.utc)
        finish = (start.replace(year=start.year + 1, month=1)
                  if start.month == 12 else start.replace(month=start.month + 1))
        async with self.factory() as session:
            rows = (await session.execute(
                select(CashEntry.kind, func.sum(CashEntry.amount_rub))
                .where(CashEntry.created_at >= start, CashEntry.created_at < finish)
                .group_by(CashEntry.kind),
            )).all()
            latest = list((await session.scalars(
                select(CashEntry).where(
                    CashEntry.created_at >= start, CashEntry.created_at < finish,
                ).order_by(CashEntry.id.desc()).limit(8),
            )).all())
        totals = {kind: int(amount) for kind, amount in rows}
        return totals.get("income", 0), totals.get("expense", 0), latest
