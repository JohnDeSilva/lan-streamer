"""add_last_played_at

Revision ID: ce128c6d8aec
Revises: fa4ad8226f3a
Create Date: 2026-05-26 12:11:43.404096

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ce128c6d8aec"
down_revision: str | Sequence[str] | None = "fa4ad8226f3a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "episodes",
        sa.Column("last_played_at", sa.Integer(), nullable=True, server_default="0"),
    )
    op.add_column(
        "movies",
        sa.Column("last_played_at", sa.Integer(), nullable=True, server_default="0"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("episodes", "last_played_at")
    op.drop_column("movies", "last_played_at")
