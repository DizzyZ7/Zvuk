"""Optimize download status lookup by user and content key.

Revision ID: 0006
Revises: 0005
"""
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_download_history_user_key_status",
        "download_history",
        ["user_id", "cache_key", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_download_history_user_key_status", table_name="download_history",
    )
