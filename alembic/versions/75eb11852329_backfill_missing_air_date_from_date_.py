"""backfill_missing_air_date_from_date_added

Revision ID: 75eb11852329
Revises: c4d5e6f7a8b9
Create Date: 2026-11-27 21:27:25.233244

"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "75eb11852329"
down_revision: str | Sequence[str] | None = "c4d5e6f7a8b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Backfill missing episode air_date, movie year, and smart_row_cache air_date from date_added."""
    op.execute(
        sa.text(
            "UPDATE episodes "
            "SET air_date = strftime('%Y-%m-%d', date_added, 'unixepoch') "
            "WHERE (air_date IS NULL OR air_date = '') "
            "AND date_added IS NOT NULL AND date_added > 0"
        )
    )
    op.execute(
        sa.text(
            "UPDATE movies "
            "SET year = CAST(strftime('%Y', date_added, 'unixepoch') AS INTEGER) "
            "WHERE (year IS NULL OR year = 0) "
            "AND date_added IS NOT NULL AND date_added > 0"
        )
    )
    op.execute(
        sa.text(
            "UPDATE smart_row_cache "
            "SET air_date = CASE "
            "    WHEN item_type = 'movie' THEN strftime('%Y', date_added, 'unixepoch') "
            "    ELSE strftime('%Y-%m-%d', date_added, 'unixepoch') "
            "END "
            "WHERE (air_date IS NULL OR air_date = '') "
            "AND date_added IS NOT NULL AND date_added > 0"
        )
    )


def downgrade() -> None:
    """Data-only backfill; no schema changes to revert."""
