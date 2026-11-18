"""Accessible privacy and terms summaries for users."""
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router(name="legal")


@router.message(Command("privacy"), F.chat.type == "private")
async def privacy(message: Message) -> None:
    await message.answer(
        "🔐 Данные Zvuk\n\n"
        "Храним Telegram ID, ник (если есть), историю запросов и скачиваний, "
        "сохраненные ссылки из /library, данные о платежах Stars и срок Premium. "
        "Redis временно хранит кэш, лимиты и задачи.\n\n"
        "Если вы отправляете аудио или видео на распознавание, короткий звуковой "
        "фрагмент передается сервису AudD. Для поиска используем открытые метаданные "
        "YouTube, Spotify и Deezer.\n\n"
        "Удаление временных файлов производится автоматически при штатной обработке. "
        "Записи PostgreSQL пока не очищаются автоматически. Для запроса удаления "
        "личных данных или уточнения условий напишите в /paysupport."
    )


@router.message(Command("terms"), F.chat.type == "private")
async def terms(message: Message) -> None:
    await message.answer(
        "📜 Условия использования Zvuk\n\n"
        "Бот помогает находить информацию о музыке и обрабатывать доступные файлы. "
        "Используйте скачивание только для контента, на который у вас есть права, "
        "с учетом правил площадок и применимого законодательства.\n\n"
        "Premium оплачивается отдельно через Telegram Stars за функции бота "
        "(отсутствие рекламной подписи на срок подписки), а не за доступ к "
        "чужим произведениям. Это разовая покупка без автопродления.\n\n"
        "По вопросам доступа, платежей и возвратов используйте /paysupport."
    )
