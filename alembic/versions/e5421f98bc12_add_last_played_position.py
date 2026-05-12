"""add_last_played_position

Revision ID: e5421f98bc12
Revises: 8dbcde9fc7de
Create Date: 2026-05-12 14:38:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e5421f98bc12"
down_revision: Union[str, Sequence[str], None] = "8dbcde9fc7de"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "episodes", sa.Column("last_played_position", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("episodes", "last_played_position")
