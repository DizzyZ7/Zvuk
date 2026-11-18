"""Private admin commands for manually sold advertising campaigns."""
from urllib.parse import urlsplit

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from app.bot.admin import AdminOnly
from app.services.repository import Repository

router = Router(name="campaigns")
router.message.filter(AdminOnly())


@router.message(Command("campaigns"), F.chat.type == "private")
async def campaigns_list(message: Message, repo: Repository) -> None:
    rows = await repo.list_campaigns()
    if not rows:
        await message.answer(
            "📢 Кампаний пока нет. Добавление:\n"
            "/campaign_add Название | Подпись | https://example.com | 1000\n"
            "Лимит 0 означает без ограничений."
        )
        return
    lines = ["📊 Рекламные размещения (счетчик отправленных подписей):"]
    for c in rows:
        limit = "∞" if c.impressions_limit is None else str(c.impressions_limit)
        status = "🟢" if c.enabled else "⚪"
        lines.append(f"{status} #{c.id} {c.label[:38]} — {c.impressions}/{limit}")
    lines.append("Управление: /campaign_on ID или /campaign_off ID")
    await message.answer("\n".join(lines)[:3900])


@router.message(Command("campaign_add"), F.chat.type == "private")
async def campaign_add(message: Message, repo: Repository) -> None:
    raw = (message.text or "").partition(" ")[2]
    parts = [p.strip() for p in raw.split("|")]
    if len(parts) != 4:
        await message.answer(
            "Формат: /campaign_add Название | Подпись | https://example.com | 1000"
        )
        return
    label, caption, url, limit = parts
    try:
        parsed = urlsplit(url)
        amount = int(limit)
        if (
            not 1 <= len(label) <= 80
            or not 1 <= len(caption) <= 850
            or parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or amount < 0
            or amount > 10_000_000
        ):
            raise ValueError("invalid campaign")
        campaign_id = await repo.add_campaign(
            label=label, caption=caption, target_url=url,
            impressions_limit=amount or None,
        )
    except ValueError:
        await message.answer(
            "Ошибка данных. Нужны название, подпись, HTTPS-ссылка и лимит от 0 до 10000000."
        )
        return
    await message.answer(
        f"✅ Кампания #{campaign_id} сохранена и включена. Статистика: /campaigns"
    )


@router.message(Command("campaign_on", "campaign_off"), F.chat.type == "private")
async def campaign_toggle(message: Message, repo: Repository) -> None:
    arg = (message.text or "").partition(" ")[2].strip()
    if not arg.isdecimal():
        await message.answer("Пример: /campaign_off 5")
        return
    enabled = (message.text or "").split()[0].split("@")[0] == "/campaign_on"
    ok = await repo.set_campaign_enabled(int(arg), enabled=enabled)
    await message.answer(
        ("✅ Кампания включена." if enabled else "✅ Кампания остановлена.")
        if ok else "Кампания не найдена."
    )
