"""Private financial operations dashboard with manual RUB receipts and expenses."""
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.bot.admin import AdminOnly
from app.services.cash_ledger import CashLedger
from app.services.repository import Repository

router = Router(name="economics")
router.message.filter(AdminOnly())
router.callback_query.filter(AdminOnly())


async def economy_text(ledger: CashLedger, repo: Repository) -> str:
    income, expenses, recent = await ledger.month()
    active, payments, stars = await repo.premium_stats()
    lines = [
        "💰 Экономика Zvuk — текущий месяц (UTC)",
        f"Получено: {income:,} ₽",
        f"Оплачено расходов: {expenses:,} ₽",
        f"Разница до налогов: {income - expenses:+,} ₽",
        "",
        f"Активных Premium: {active}",
        f"Платежей Stars (без возвратов): {payments}",
        f"Поступления: {stars} Stars — отдельно, без пересчета в рубли",
        "",
        "Последние операции:",
    ]
    if not recent:
        lines.append("Записей пока нет.")
    for row in recent:
        sign = "+" if row.kind == "income" else "−"
        lines.append(f"#{row.id}: {sign}{row.amount_rub} ₽ · {row.category[:35]}")
    lines.extend([
        "",
        "/income 1500 | Реклама | Название заказчика",
        "/expense 1100 | Хостинг | VPS",
        "Учитываются только вручную подтвержденные денежные операции.",
    ])
    return "\n".join(lines)[:3900]


@router.message(Command("economics"))
async def economics_command(
    message: Message, ledger: CashLedger, repo: Repository,
) -> None:
    await message.answer(await economy_text(ledger, repo))


@router.callback_query(F.data == "adm:economics")
async def economics_button(
    callback: CallbackQuery, ledger: CashLedger, repo: Repository,
) -> None:
    if isinstance(callback.message, Message):
        await callback.message.answer(await economy_text(ledger, repo))
    await callback.answer()


async def create_entry(
    message: Message, ledger: CashLedger, kind: str,
) -> None:
    raw = (message.text or "").partition(" ")[2].strip()
    parts = [value.strip() for value in raw.split("|", maxsplit=2)]
    if len(parts) < 2:
        await message.answer(
            "/income 1500 | Реклама | Заказчик\n"
            "/expense 1100 | Хостинг | VPS"
        )
        return
    try:
        if not parts[0].isdecimal():
            raise ValueError("Сумма должна быть целым числом рублей.")
        amount = int(parts[0])
        category = parts[1]
        note = parts[2] if len(parts) > 2 else ""
        entry_id = await ledger.add(kind, amount, category, note)
    except ValueError as exc:
        await message.answer(f"Некорректная запись: {exc}")
        return
    await message.answer(
        f"✅ Операция #{entry_id} записана. Отчет: /economics"
    )


@router.message(Command("income"))
async def record_income(message: Message, ledger: CashLedger) -> None:
    await create_entry(message, ledger, "income")


@router.message(Command("expense"))
async def record_expense(message: Message, ledger: CashLedger) -> None:
    await create_entry(message, ledger, "expense")
