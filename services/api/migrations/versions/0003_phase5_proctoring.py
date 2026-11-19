"""Add consent, sampled-inference sessions, observations, and review decisions."""

from alembic import op

from app import models  # noqa: F401 - register ORM tables with shared metadata
from app.db.base import Base

revision = "0003_phase5_proctoring"
down_revision = "0002_phase2_domain"
branch_labels = None
depends_on = None

PHASE5_TABLES = (
    "proctoring_consents",
    "proctoring_sessions",
    "proctoring_events",
    "review_decisions",
    "audit_logs",
)


def upgrade() -> None:
    tables = [Base.metadata.tables[name] for name in PHASE5_TABLES]
    Base.metadata.create_all(bind=op.get_bind(), tables=tables)


def downgrade() -> None:
    bind = op.get_bind()
    tables = [Base.metadata.tables[name] for name in reversed(PHASE5_TABLES)]
    Base.metadata.drop_all(bind=bind, tables=tables, checkfirst=True)
