from redis.asyncio import Redis
from redis.exceptions import ResponseError

DOWNLOAD_STREAM = "zvuk:downloads"
BROADCAST_STREAM = "zvuk:broadcasts"
GROUP = "workers"

async def ensure_groups(redis: Redis) -> None:
    for stream in (DOWNLOAD_STREAM, BROADCAST_STREAM):
        try:
            await redis.xgroup_create(stream, GROUP, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

async def enqueue_download(redis: Redis, job_id: str) -> None:
    await redis.xadd(DOWNLOAD_STREAM, {"job_id": job_id})

async def enqueue_broadcast(redis: Redis, job_id: str) -> None:
    await redis.xadd(BROADCAST_STREAM, {"job_id": job_id})

async def release_lock(redis: Redis, key: str, token: str) -> None:
    await redis.eval(
        "if redis.call('get',KEYS[1]) == ARGV[1] then "
        "return redis.call('del',KEYS[1]) else return 0 end",
        1, key, token,
    )
