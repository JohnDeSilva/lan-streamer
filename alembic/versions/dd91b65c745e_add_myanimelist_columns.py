"""add_myanimelist_columns

Revision ID: dd91b65c745e
Revises: 90c0fcb92ee7
Create Date: 2026-06-06 13:53:27.113423

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "dd91b65c745e"
down_revision: Union[str, Sequence[str], None] = "90c0fcb92ee7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("seasons", sa.Column("myanimelist_id", sa.Integer(), nullable=True))
    op.add_column(
        "episodes", sa.Column("myanimelist_anime_id", sa.Integer(), nullable=True)
    )
    op.add_column(
        "episodes", sa.Column("myanimelist_episode_number", sa.Integer(), nullable=True)
    )
    op.add_column(
        "movies", sa.Column("myanimelist_anime_id", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("movies", "myanimelist_anime_id")
    op.drop_column("episodes", "myanimelist_episode_number")
    op.drop_column("episodes", "myanimelist_anime_id")
    op.drop_column("seasons", "myanimelist_id")
