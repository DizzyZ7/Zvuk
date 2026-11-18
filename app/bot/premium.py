"""User-facing Telegram Stars Premium purchase and payment confirmation."""
import asyncio
import logging

from sqlalchemy.exc import SQLAlchemyError

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import LabeledPrice, Message, PreCheckoutQuery

from app.core.config import Settings
from app.services.premium import InvalidPayment, PremiumService
from app.services.user_service import UserService

log = logging.getLogger(__name__)
router = Router(name="premium")


@router.message(Command("premium"), F.chat.type == "private")
async def premium_offer(
    message: Message, bot: Bot, settings: Settings,
    premium: PremiumService, users: UserService,
) -> None:
    if not message.from_user:
        return
    if not settings.premium_enabled:
        await message.answer(
            "🌟 Premium пока готовится к запуску. Бесплатные функции работают."
        )
        return
    if not settings.support_username.strip():
        await message.answer("Оплата временно недоступна. Контакт поддержки не настроен.")
        return
    await users.register(message.from_user)
    expires = await premium.active_until(message.from_user.id)
    info = (
        f"🌟 Premium действует до {expires:%d.%m.%Y %H:%M} UTC.\n"
        if expires else "🌟 Premium — без рекламных подписей под файлами.\n"
    )
    payload = await premium.create_order(message.from_user.id, settings.premium_price_stars)
    await message.answer(
        info + f"Еще {settings.premium_days} дней за {settings.premium_price_stars} Stars. "
        "Оплата только за функции бота, не за музыку."
    )
    await bot.send_invoice(
        chat_id=message.chat.id,
        title="Zvuk Premium",
        description=f"Отключение рекламных подписей на {settings.premium_days} дней.",
        payload=payload,
        currency="XTR",
        prices=[LabeledPrice(
            label=f"Premium {settings.premium_days} дней",
            amount=settings.premium_price_stars,
        )],
        provider_token="",
    )


@router.pre_checkout_query()
async def premium_checkout(
    query: PreCheckoutQuery, premium: PremiumService, settings: Settings,
) -> None:
    valid = bool(settings.premium_enabled and settings.support_username.strip())
    if valid:
        valid = await premium.validate_checkout(
            query.invoice_payload, query.from_user.id,
            query.currency, query.total_amount,
        )
    await query.answer(
        ok=valid,
        error_message=None if valid else "Счет устарел или сумма не совпадает. Откройте /premium заново.",
    )


@router.message(F.successful_payment)
async def premium_success(
    message: Message, premium: PremiumService,
) -> None:
    if not message.from_user or not message.successful_payment:
        return
    payment = message.successful_payment
    for attempt in range(3):
        try:
            expiry, _ = await premium.complete(
                payment.invoice_payload, message.from_user.id,
                payment.currency, payment.total_amount,
                payment.telegram_payment_charge_id,
            )
            await message.answer(
                f"✅ Zvuk Premium активен до {expiry:%d.%m.%Y %H:%M} UTC. "
                "Рекламные подписи больше не показываются."
            )
            return
        except InvalidPayment:
            log.exception("Invalid paid invoice for user=%s", message.from_user.id)
            break
        except SQLAlchemyError:
            log.exception(
                "Payment database unavailable user=%s attempt=%s",
                message.from_user.id, attempt + 1,
            )
            if attempt < 2:
                await asyncio.sleep(attempt + 1)
    await message.answer(
        "Telegram подтвердил платеж, но автоматическое начисление недоступно. "
        "Напишите /paysupport и сохраните квитанцию для проверки."
    )


@router.message(Command("paysupport"), F.chat.type == "private")
async def payment_support(message: Message, settings: Settings) -> None:
    support = f"@{settings.support_username.lstrip(chr(64))}" if settings.support_username else (
        "Напишите администратору бота через доступный контакт."
    )
    await message.answer(
        "Вопросы по оплате, возвратам и доступу к Premium: " + support +
        "\nНе пересылайте посторонним токены, пароли и платежные данные."
    )
