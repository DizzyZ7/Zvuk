"""Durable aiogram FSM storage using the shared PostgreSQL AppState table."""
import hashlib
import json

from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, StateType, StorageKey

from app.core.state import StateStore


class PostgresFSMStorage(BaseStorage):
    def __init__(self, state: StateStore):
        self.state = state

    @staticmethod
    def key(key: StorageKey, kind: str) -> str:
        fingerprint = hashlib.sha256(repr(key).encode()).hexdigest()
        return f"fsm:{kind}:{fingerprint}"

    async def set_state(self, key: StorageKey, state: StateType = None) -> None:
        name = self.key(key, "state")
        if state is None:
            await self.state.delete(name)
            return
        value = state.state if isinstance(state, State) else str(state)
        await self.state.set(name, value, ex=604800)

    async def get_state(self, key: StorageKey) -> str | None:
        return await self.state.get(self.key(key, "state"))

    async def set_data(self, key: StorageKey, data: dict) -> None:
        name = self.key(key, "data")
        if not data:
            await self.state.delete(name)
        else:
            await self.state.set(name, json.dumps(data), ex=604800)

    async def get_data(self, key: StorageKey) -> dict:
        raw = await self.state.get(self.key(key, "data"))
        return json.loads(raw) if raw else {}

    async def close(self) -> None:
        # Connections are owned by the shared SQLAlchemy engine.
        pass
