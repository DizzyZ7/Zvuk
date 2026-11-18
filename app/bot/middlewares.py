import logging
from typing import Any, Awaitable, Callable
from aiogram import BaseMiddleware, Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message, TelegramObject
from redis.asyncio import Redis
from app.core.config import Settings
from app.bot.keyboards import subscribe_keyboard
from app.services.repository import Repository
from app.services.urls import LINK_RE

log = logging.getLogger(__name__)

def is_search_request(event: TelegramObject) -> bool:
    return (
        isinstance(event, Message)
        and event.chat.type == "private"
        and bool(event.text)
        and not event.text.startswith("/")
        and not LINK_RE.search(event.text)
    )


def is_download_request(event: TelegramObject) -> bool:
    if isinstance(event, Message):
        return event.chat.type == "private" and bool(event.text and LINK_RE.search(event.text))
    if isinstance(event, CallbackQuery):
        return bool(event.data and event.data.startswith(("fmt:", "find:", "libplay:")))
    return False

class ThrottleMiddleware(BaseMiddleware):
    async def __call__(
        self, handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject, data: dict[str, Any],
    ) -> Any:
        if not is_download_request(event) and not is_search_request(event):
            return await handler(event, data)
        user = getattr(event, "from_user", None)
        settings: Settings = data["settings"]
        if user and user.id not in settings.admin_ids:
            redis: Redis = data["redis"]
            # Choosing a format should be immediate after sending a link.
            # A separate callback limiter guards against repeated taps.
            scope = (
                "format" if isinstance(event, CallbackQuery)
                else ("search" if is_search_request(event) else "link")
            )
            allowed = await redis.set(
                f"throttle:{scope}:{user.id}", "1",
                ex=6 if scope == "search" else 3, nx=True,
            )
            if not allowed:
                if isinstance(event, CallbackQuery):
                    await event.answer("Не чаще одного запроса в 3 секунды.", show_alert=False)
                elif isinstance(event, Message):
                    await event.answer("⏳ Слишком часто. Повторите запрос через несколько секунд.")
                return None
        return await handler(event, data)

class SponsorMiddleware(BaseMiddleware):
    async def __call__(
        self, handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject, data: dict[str, Any],
    ) -> Any:
        if not is_download_request(event):
            return await handler(event, data)
        settings: Settings = data["settings"]
        user = getattr(event, "from_user", None)
        if user is None or user.id in settings.admin_ids:
            return await handler(event, data)
        repo: Repository = data["repo"]
        bot: Bot = data["bot"]
        channels = await repo.sponsors()
        if not channels:
            return await handler(event, data)
        missing = []
        for channel in channels:
            try:
                member = await bot.get_chat_member(chat_id=channel.chat_id, user_id=user.id)
                status = member.status
                valid = status in (ChatMemberStatus.MEMBER,
                                   ChatMemberStatus.ADMINISTRATOR,
                                   ChatMemberStatus.CREATOR)
                if status == ChatMemberStatus.RESTRICTED:
                    valid = bool(getattr(member, "is_member", False))
                if not valid:
                    missing.append(channel)
            except TelegramAPIError:
                log.exception("Subscription check failed for chat %s", channel.chat_id)
                if isinstance(event, CallbackQuery):
                    await event.answer("Проверка подписки недоступна. Сообщите администратору.",
                                       show_alert=True)
                else:
                    await event.answer("Не могу проверить подписки. Сообщите администратору.")
                return None
        if missing:
            if isinstance(event, CallbackQuery):
                await event.answer("Сначала подпишитесь на каналы.", show_alert=True)
                if isinstance(event.message, Message):
                    await event.message.answer(
                        "Для скачивания подпишитесь на каналы:",
                        reply_markup=subscribe_keyboard(missing),
                    )
            else:
                await event.answer(
                    "Для скачивания подпишитесь на каналы:",
                    reply_markup=subscribe_keyboard(missing),
                )
            return None
        return await handler(event, data)

async def subscription_missing(
    bot: Bot, user_id: int, repo: Repository,
) -> tuple[list, bool]:
    missing = []
    for channel in await repo.sponsors():
        try:
            member = await bot.get_chat_member(channel.chat_id, user_id)
            status = member.status
            valid = status in (ChatMemberStatus.MEMBER,
                               ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR)
            if status == ChatMemberStatus.RESTRICTED:
                valid = bool(getattr(member, "is_member", False))
            if not valid:
                missing.append(channel)
        except TelegramAPIError:
            log.exception("Sponsor channel inaccessible: %s", channel.chat_id)
            return [], False
    return missing, True
