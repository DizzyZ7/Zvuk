from app.services.repository import Repository

class AdManager:
    def __init__(self, repository: Repository):
        self.repository = repository

    async def caption(self) -> str | None:
        text = (await self.repository.ad_text()).strip()
        return text[:1024] if text else None
