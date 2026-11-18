from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.bot.economics import economy_text
from app.services.cash_ledger import CashLedger


@pytest.mark.asyncio
async def test_economics_reports_actual_rub_and_separate_stars():
    ledger = SimpleNamespace(month=AsyncMock(return_value=(3000, 1200, [])))
    repo = SimpleNamespace(premium_stats=AsyncMock(return_value=(5, 8, 992)))
    text = await economy_text(ledger, repo)
    assert "3,000 ₽" in text
    assert "1,200 ₽" in text
    assert "+1,800 ₽" in text
    assert "992 Stars" in text
    assert "без пересчета" in text


@pytest.mark.asyncio
async def test_cash_entry_validation_without_db():
    ledger = CashLedger(factory=None)
    with pytest.raises(ValueError):
        await ledger.add("expense", 0, "Hosting")
    with pytest.raises(ValueError):
        await ledger.add("invoice", 500, "Advertising")
    with pytest.raises(ValueError):
        await ledger.add("income", 100, " ")
