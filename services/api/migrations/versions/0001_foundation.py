"""Establish migration history before domain schema is introduced.

Revision ID: 0001_foundation
Revises:
"""

revision = "0001_foundation"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Domain tables are intentionally introduced in Phase 2.
    pass


def downgrade() -> None:
    pass
