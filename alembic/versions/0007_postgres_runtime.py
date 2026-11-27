"""Native PostgreSQL ephemeral state, durable queue leases and delivery receipts.

Revision ID: 0007
Revises: 0006
"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "download_history", sa.Column("lease_until", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "broadcasts", sa.Column("lease_until", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "app_state",
        sa.Column("key", sa.String(255), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_app_state_expires_at", "app_state", ["expires_at"])
    op.create_table(
        "delivery_receipts",
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"),
                  primary_key=True),
        sa.Column("cache_key", sa.String(64), primary_key=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
    )
    # Preserve existing completed deliveries before old job logs are purged.
    op.execute("""
        INSERT INTO delivery_receipts (user_id, cache_key, delivered_at)
        SELECT user_id, cache_key,
               COALESCE(finished_at, created_at)
        FROM download_history
        WHERE status = 'success'
        ON CONFLICT (user_id, cache_key) DO NOTHING
    """)
    op.create_index(
        "ix_download_queue_claim",
        "download_history", ["created_at"],
        postgresql_where=sa.text("status IN ('queued', 'processing')"),
    )


def downgrade() -> None:
    op.drop_index("ix_download_queue_claim", table_name="download_history")
    op.drop_table("delivery_receipts")
    op.drop_index("ix_app_state_expires_at", table_name="app_state")
    op.drop_table("app_state")
    op.drop_column("broadcasts", "lease_until")
    op.drop_column("download_history", "lease_until")
