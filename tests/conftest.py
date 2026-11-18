import os

# Test imports create global Settings; supply synthetic values, never real credentials.
os.environ.setdefault("BOT_TOKEN", "123456:test_token")
os.environ.setdefault("TELEGRAM_API_ID", "123456")
os.environ.setdefault("TELEGRAM_API_HASH", "test_hash")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/testdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
