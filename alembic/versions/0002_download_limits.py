"""Index queue capacity lookups.

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_download_history_user_status", "download_history", ["user_id", "status"]
    )


def downgrade() -> None:
    op.drop_index("ix_download_history_user_status", table_name="download_history")
