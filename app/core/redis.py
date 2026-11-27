from redis.asyncio import Redis
from app.core.config import settings

def make_redis() -> Redis:
    return Redis.from_url(settings.redis_url, decode_responses=True, health_check_interval=30, socket_keepalive=True)
