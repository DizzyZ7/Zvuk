from aiogram.types import User as TelegramUser
from app.services.repository import Repository

class UserService:
    def __init__(self, repository: Repository):
        self.repository = repository

    async def register(self, user: TelegramUser) -> None:
        await self.repository.touch_user(user.id, user.username)
