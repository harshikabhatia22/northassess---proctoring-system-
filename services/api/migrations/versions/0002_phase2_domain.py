"""Create Phase 2 identity and assessment tables."""

from alembic import op
from sqlalchemy import insert

from app import models
from app.db.base import Base

revision = "0002_phase2_domain"
down_revision = "0001_foundation"
branch_labels = None
depends_on = None

PHASE2_TABLES = (
    "roles",
    "user_roles",
    "users",
    "refresh_sessions",
    "bootstrap_state",
    "courses",
    "course_memberships",
    "exams",
    "questions",
    "exam_assignments",
    "exam_attempts",
    "answers",
)


def upgrade() -> None:
    tables = [Base.metadata.tables[name] for name in PHASE2_TABLES]
    Base.metadata.create_all(bind=op.get_bind(), tables=tables)
    op.execute(
        "INSERT INTO roles (name) VALUES "
        "('student'), ('instructor'), ('administrator'), ('ml_maintainer')"
    )
    op.get_bind().execute(insert(models.BootstrapState).values(id=1, initialized=False))


def downgrade() -> None:
    tables = [Base.metadata.tables[name] for name in reversed(PHASE2_TABLES)]
    Base.metadata.drop_all(bind=op.get_bind(), tables=tables)
