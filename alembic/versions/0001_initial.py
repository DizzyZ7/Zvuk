"""Initial schema.

Revision ID: 0001
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("username", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("is_blocked", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.create_index("ix_users_last_seen", "users", ["last_seen"])
    op.create_table(
        "media_cache",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("file_id", sa.Text(), nullable=False),
        sa.Column("media_type", sa.String(8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "download_history",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("cache_key", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("cache_hit", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_download_history_user_created", "download_history", ["user_id", "created_at"])
    op.create_table(
        "ad_posts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.create_table(
        "sponsor_channels",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("join_url", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.create_table(
        "broadcasts",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("admin_id", sa.BigInteger(), nullable=False),
        sa.Column("source_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("source_message_id", sa.Integer(), nullable=False),
        sa.Column("progress_message_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("processed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_user_id", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

def downgrade() -> None:
    op.drop_table("broadcasts")
    op.drop_table("sponsor_channels")
    op.drop_table("ad_posts")
    op.drop_index("ix_download_history_user_created", table_name="download_history")
    op.drop_table("download_history")
    op.drop_table("media_cache")
    op.drop_index("ix_users_last_seen", table_name="users")
    op.drop_table("users")
