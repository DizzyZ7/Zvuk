"""Music library, Premium orders/grants and advertiser campaigns.

Revision ID: 0004
Revises: 0003
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "saved_tracks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("url_hash", sa.String(64), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("artist", sa.String(255), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "url_hash", name="uq_saved_user_hash"),
    )
    op.create_index("ix_saved_tracks_user_id", "saved_tracks", ["user_id"])
    op.create_table(
        "premium_grants",
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "premium_orders",
        sa.Column("payload", sa.String(96), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("stars", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_premium_orders_user_id", "premium_orders", ["user_id"])
    op.create_table(
        "premium_payments",
        sa.Column("charge_id", sa.String(255), primary_key=True),
        sa.Column("order_payload", sa.String(96), sa.ForeignKey("premium_orders.payload"),
                  nullable=False, unique=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("stars", sa.Integer(), nullable=False),
        sa.Column("refunded", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_premium_payments_user_id", "premium_payments", ["user_id"])
    op.create_table(
        "ad_campaigns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("caption", sa.Text(), nullable=False),
        sa.Column("target_url", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("impressions_limit", sa.Integer()),
        sa.Column("impressions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("ad_campaigns")
    op.drop_index("ix_premium_payments_user_id", table_name="premium_payments")
    op.drop_table("premium_payments")
    op.drop_index("ix_premium_orders_user_id", table_name="premium_orders")
    op.drop_table("premium_orders")
    op.drop_table("premium_grants")
    op.drop_index("ix_saved_tracks_user_id", table_name="saved_tracks")
    op.drop_table("saved_tracks")
