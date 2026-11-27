"""Legacy module: PostgreSQL is now the only persistence service.

No Redis client is needed. Existing integrations should import StateStore.
"""
from app.core.state import StateStore

__all__ = ["StateStore"]
