from datetime import datetime
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

class MediaCache(Base):
    __tablename__ = "media_cache"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    file_id: Mapped[str] = mapped_column(Text, nullable=False)
    media_type: Mapped[str] = mapped_column(String(8), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class DownloadHistory(Base):
    __tablename__ = "download_history"
    __table_args__ = (
        Index("ix_download_history_user_created", "user_id", "created_at"),
        Index("ix_download_history_user_status", "user_id", "status"),
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    cache_key: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    retry_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class AdPost(Base):
    __tablename__ = "ad_posts"
    id: Mapped[int] = mapped_column(primary_key=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

class SponsorChannel(Base):
    __tablename__ = "sponsor_channels"
    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    join_url: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

class Broadcast(Base):
    __tablename__ = "broadcasts"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    admin_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_message_id: Mapped[int] = mapped_column(Integer, nullable=False)
    progress_message_id: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    total: Mapped[int] = mapped_column(Integer, nullable=False)
    processed: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    failed: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_user_id: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
