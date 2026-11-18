import logging
from urllib.parse import urlsplit

from aiogram import Bot, F, Router
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, Filter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.bot.keyboards import admin_keyboard, broadcast_confirmation, broadcast_stop_keyboard
from app.core.config import Settings
from app.services.health import health_status
from app.services.queue import enqueue_broadcast
from app.services.repository import Repository

log = logging.getLogger(__name__)
router = Router(name="admin")

class AdminOnly(Filter):
    async def __call__(self, event: Message | CallbackQuery, settings: Settings) -> bool:
        if event.from_user is None or event.from_user.id not in settings.admin_ids:
            return False
        chat_message = event if isinstance(event, Message) else event.message
        return isinstance(chat_message, Message) and chat_message.chat.type == "private"

router.message.filter(AdminOnly())
router.callback_query.filter(AdminOnly())

class AdminState(StatesGroup):
    adding_channel = State()
    editing_ad = State()
    broadcasting = State()
    confirm_broadcast = State()

@router.message(Command("health"))
async def check_health_command(
    message: Message, bot: Bot, redis: Redis, repo: Repository,
) -> None:
    report = await health_status(bot, redis, repo)
    await message.answer(report.display())


@router.callback_query(F.data == "adm:health")
async def check_health_button(
    callback: CallbackQuery, bot: Bot, redis: Redis, repo: Repository,
) -> None:
    report = await health_status(bot, redis, repo)
    if isinstance(callback.message, Message):
        await callback.message.answer(report.display())
    await callback.answer()


@router.message(Command("admin"))
async def admin_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("⚙️ Управление Zvuk", reply_markup=admin_keyboard())

@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Отменено.", reply_markup=admin_keyboard())

@router.callback_query(F.data == "adm:home")
async def back(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if isinstance(callback.message, Message):
        await callback.message.edit_text("⚙️ Управление Zvuk", reply_markup=admin_keyboard())
    await callback.answer()

@router.callback_query(F.data == "adm:stats")
async def show_stats(callback: CallbackQuery, repo: Repository) -> None:
    total, active, downloads, cached = await repo.stats()
    try:
        queued_downloads, queued_broadcasts = await repo.queue_depths()
        queues = f"{queued_downloads} загрузок / {queued_broadcasts} рассылок"
    except RedisError:
        queues = "данные временно недоступны"
    if isinstance(callback.message, Message):
        await callback.message.answer(
            f"📊 Пользователи: {total}\nЗа 24 часа: {active}\n"
            f"Успешных скачиваний: {downloads}\nОтдано из кэша: {cached}\n"
            f"В очереди: {queues}"
        )
    await callback.answer()

@router.callback_query(F.data == "adm:channels")
async def list_channels(callback: CallbackQuery, repo: Repository) -> None:
    channels = await repo.sponsors()
    rows = [[InlineKeyboardButton(text=f"❌ Удалить {c.title[:30]}",
                                  callback_data=f"adm:del:{c.id}")] for c in channels]
    rows.append([InlineKeyboardButton(text="➕ Добавить", callback_data="adm:add")])
    rows.append([InlineKeyboardButton(text="↩️ Меню", callback_data="adm:home")])
    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            "Спонсорские каналы (бот должен быть администратором):",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )
    await callback.answer()

@router.callback_query(F.data == "adm:add")
async def add_channel_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminState.adding_channel)
    if isinstance(callback.message, Message):
        await callback.message.answer(
            "Отправьте @username канала или строку: -1001234567890 | https://t.me/+invite\n"
            "Для публичного канала ссылка сформируется автоматически. /cancel — отмена."
        )
    await callback.answer()

@router.message(AdminState.adding_channel)
async def add_channel(message: Message, bot: Bot, repo: Repository, state: FSMContext) -> None:
    value = (message.text or "").strip()
    parts = [p.strip() for p in value.split("|", 1)]
    chat_ref = parts[0]
    if not chat_ref.startswith("@") and not chat_ref.startswith("-100"):
        await message.answer("Укажите @username либо числовой -100... ID канала.")
        return
    try:
        chat = await bot.get_chat(int(chat_ref) if chat_ref.startswith("-100") else chat_ref)
        me = await bot.get_me()
        membership = await bot.get_chat_member(chat.id, me.id)
        if chat.type != "channel" or membership.status not in (
            ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR
        ):
            await message.answer("Бот должен быть администратором канала.")
            return
        url = parts[1] if len(parts) > 1 else (
            f"https://t.me/{chat.username}" if chat.username else ""
        )
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname != "t.me" or not parsed.path.strip("/"):
            await message.answer("Укажите действительную ссылку приглашения https://t.me/...")
            return
        await repo.sponsor_add(chat.id, chat.title or str(chat.id), url)
    except (ValueError, TelegramAPIError) as exc:
        log.warning("Sponsor configuration failed: %s", exc)
        await message.answer("Не удалось найти канал или проверить права бота.")
        return
    await state.clear()
    await message.answer("✅ Канал сохранен.", reply_markup=admin_keyboard())

@router.callback_query(F.data.startswith("adm:del:"))
async def remove_channel(callback: CallbackQuery, repo: Repository) -> None:
    try:
        channel_id = int((callback.data or "").split(":")[2])
    except (ValueError, IndexError):
        await callback.answer("Некорректный ID.", show_alert=True)
        return
    await repo.sponsor_remove(channel_id)
    await list_channels(callback, repo)

@router.callback_query(F.data == "adm:campaigns")
async def show_campaigns_button(callback: CallbackQuery, repo: Repository) -> None:
    rows = await repo.list_campaigns()
    if isinstance(callback.message, Message):
        if not rows:
            await callback.message.answer(
                "Кампаний нет. Создание: /campaign_add Название | Подпись | "
                "https://example.com | 1000"
            )
        else:
            lines = ["📈 Рекламные кампании:"]
            for c in rows[:20]:
                limit = "∞" if c.impressions_limit is None else str(c.impressions_limit)
                lines.append(
                    f"#{c.id} {'🟢' if c.enabled else '⚪'} {c.label[:35]} "
                    f"{c.impressions}/{limit}"
                )
            lines.append("/campaigns — весь список и управление")
            await callback.message.answer("\n".join(lines))
    await callback.answer()


@router.callback_query(F.data == "adm:ads")
async def prompt_ad(callback: CallbackQuery, state: FSMContext, repo: Repository) -> None:
    await state.set_state(AdminState.editing_ad)
    current = await repo.ad_text()
    if isinstance(callback.message, Message):
        await callback.message.answer(
            "Введите новую рекламную подпись (до 1024 символов). "
            "Отправьте '-' для отключения.\n\nТекущая:\n" + (current or "(отключена)")
        )
    await callback.answer()

@router.message(AdminState.editing_ad)
async def save_ad(message: Message, state: FSMContext, repo: Repository) -> None:
    text = (message.text or "").strip()
    if text == "-":
        text = ""
    if len(text) > 1024:
        await message.answer("Максимальная длина подписи — 1024 символа.")
        return
    await repo.set_ad(text)
    await state.clear()
    await message.answer("✅ Подпись обновлена без перезапуска.", reply_markup=admin_keyboard())

@router.callback_query(F.data == "adm:broadcast")
async def prompt_broadcast(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminState.broadcasting)
    if isinstance(callback.message, Message):
        await callback.message.answer(
            "Отправьте сообщение для рассылки (текст/фото/видео). "
            "Оно будет скопировано получателям. /cancel — отмена."
        )
    await callback.answer()

@router.message(AdminState.broadcasting)
async def preview_broadcast(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    await state.update_data(source_message_id=message.message_id)
    await state.set_state(AdminState.confirm_broadcast)
    await message.answer(
        "📨 Сообщение выше будет отправлено пользователям. Подтвердите запуск: "
        "отменить уже доставленные сообщения невозможно.",
        reply_markup=broadcast_confirmation(),
    )


@router.callback_query(AdminState.confirm_broadcast, F.data == "adm:bc:cancel")
async def abandon_broadcast(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if isinstance(callback.message, Message):
        await callback.message.edit_text("Рассылка не запускалась.")
    await callback.answer("Отменено")


@router.callback_query(AdminState.confirm_broadcast, F.data == "adm:bc:send")
async def launch_broadcast(
    callback: CallbackQuery, state: FSMContext, repo: Repository, redis: Redis,
) -> None:
    if not isinstance(callback.message, Message):
        await callback.answer("Сообщение недоступно.", show_alert=True)
        return
    if await repo.broadcast_active():
        await callback.answer("Другая рассылка уже выполняется.", show_alert=True)
        return
    data = await state.get_data()
    source_id = data.get("source_message_id")
    if not isinstance(source_id, int):
        await callback.answer("Предпросмотр устарел. Начните заново.", show_alert=True)
        await state.clear()
        return
    progress = await callback.message.answer("📨 Рассылка поставлена в очередь: 0%")
    job_id = await repo.new_broadcast(callback.from_user.id, source_id, progress.message_id)
    await progress.edit_text(
        "📨 Рассылка поставлена в очередь: 0%",
        reply_markup=broadcast_stop_keyboard(job_id),
    )
    try:
        await enqueue_broadcast(redis, job_id)
    except Exception:
        await repo.broadcast_progress(job_id, 0, 0, 0, "failed")
        await progress.edit_text("Не удалось поставить рассылку в очередь.")
        raise
    await state.clear()
    await callback.message.edit_text("✅ Рассылка запущена. Прогресс — в сообщении ниже.")
    await callback.answer()


@router.callback_query(F.data.startswith("adm:bcancel:"))
async def stop_broadcast(callback: CallbackQuery, repo: Repository) -> None:
    job_id = (callback.data or "").removeprefix("adm:bcancel:")
    if len(job_id) != 32 or any(c not in "0123456789abcdef" for c in job_id):
        await callback.answer("Некорректный идентификатор.", show_alert=True)
        return
    cancelled = await repo.cancel_broadcast(job_id, callback.from_user.id)
    if not cancelled:
        await callback.answer("Рассылка уже завершена или недоступна.", show_alert=True)
        return
    if isinstance(callback.message, Message):
        await callback.message.edit_text("🛑 Рассылка остановлена. Уже отправленные сообщения останутся у получателей.")
    await callback.answer("Остановлено")
