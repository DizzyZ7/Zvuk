"""Playlists, tracks and manual actual-cash ledger.

Revision ID: 0005
Revises: 0004
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "playlists",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_playlists_user_id", "playlists", ["user_id"])
    op.create_table(
        "playlist_tracks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("playlist_id", sa.Integer(),
                  sa.ForeignKey("playlists.id", ondelete="CASCADE"), nullable=False),
        sa.Column("url_hash", sa.String(64), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("artist", sa.String(255), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("playlist_id", "url_hash", name="uq_playlist_track_hash"),
    )
    op.create_index("ix_playlist_tracks_playlist_id", "playlist_tracks", ["playlist_id"])
    op.create_table(
        "cash_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("amount_rub", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(80), nullable=False),
        sa.Column("note", sa.String(255), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("kind IN ('income', 'expense')", name="cash_kind"),
        sa.CheckConstraint("amount_rub > 0", name="cash_amount_positive"),
    )


def downgrade() -> None:
    op.drop_table("cash_entries")
    op.drop_index("ix_playlist_tracks_playlist_id", table_name="playlist_tracks")
    op.drop_table("playlist_tracks")
    op.drop_index("ix_playlists_user_id", table_name="playlists")
    op.drop_table("playlists")
