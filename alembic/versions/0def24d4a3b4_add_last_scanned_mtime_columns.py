"""add_last_scanned_mtime_columns

Revision ID: 0def24d4a3b4
Revises: 36e082ff742e
Create Date: 2026-06-24 23:02:02.948220

"""

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "0def24d4a3b4"
down_revision: str | Sequence[str] | None = "36e082ff742e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "scanned_directories",
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("last_scanned_mtime", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("path"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("scanned_directories")
