"""Explicit, auditable retention for finalized attempt data.

The command is preview-only unless an operator supplies an approved policy
reference and confirms the destructive operation.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.session import get_session_factory
from app.models import (
    Answer,
    AuditLog,
    ExamAttempt,
    ProctoringConsent,
    ProctoringEvent,
    ProctoringSession,
    ReviewDecision,
    Role,
    User,
    user_roles,
)


def _expired_attempts(cutoff: datetime):
    return select(ExamAttempt.id).where(
        ExamAttempt.status != "in_progress",
        ExamAttempt.submitted_at.is_not(None),
        ExamAttempt.submitted_at < cutoff,
    )


def _related_ids(cutoff: datetime):
    attempt_ids = _expired_attempts(cutoff)
    session_ids = select(ProctoringSession.id).where(ProctoringSession.attempt_id.in_(attempt_ids))
    event_ids = select(ProctoringEvent.id).where(ProctoringEvent.session_id.in_(session_ids))
    return attempt_ids, session_ids, event_ids


def preview_expired_attempt_data(db: Session, cutoff: datetime) -> dict[str, int]:
    """Count rows eligible for deletion without mutating the database."""
    attempt_ids, session_ids, event_ids = _related_ids(cutoff)
    tables = {
        "review_decisions": (ReviewDecision, ReviewDecision.event_id.in_(event_ids)),
        "events": (ProctoringEvent, ProctoringEvent.session_id.in_(session_ids)),
        "sessions": (ProctoringSession, ProctoringSession.id.in_(session_ids)),
        "consents": (ProctoringConsent, ProctoringConsent.attempt_id.in_(attempt_ids)),
        "answers": (Answer, Answer.attempt_id.in_(attempt_ids)),
        "attempts": (ExamAttempt, ExamAttempt.id.in_(attempt_ids)),
    }
    return {
        name: int(db.scalar(select(func.count()).select_from(model).where(condition)) or 0)
        for name, (model, condition) in tables.items()
    }


def purge_expired_attempt_data(
    db: Session,
    cutoff: datetime,
    *,
    actor_id: str,
    approved_policy: str,
) -> dict[str, int]:
    """Delete finalized attempt data and record an aggregate audit event."""
    if not actor_id or not approved_policy.strip():
        raise ValueError("An administrator actor and approved policy reference are required")

    before = preview_expired_attempt_data(db, cutoff)
    attempt_ids, session_ids, event_ids = _related_ids(cutoff)
    db.execute(delete(ReviewDecision).where(ReviewDecision.event_id.in_(event_ids)))
    db.execute(delete(ProctoringEvent).where(ProctoringEvent.session_id.in_(session_ids)))
    db.execute(delete(ProctoringSession).where(ProctoringSession.id.in_(session_ids)))
    db.execute(delete(ProctoringConsent).where(ProctoringConsent.attempt_id.in_(attempt_ids)))
    db.execute(delete(Answer).where(Answer.attempt_id.in_(attempt_ids)))
    db.execute(delete(ExamAttempt).where(ExamAttempt.id.in_(attempt_ids)))
    db.add(
        AuditLog(
            actor_id=actor_id,
            action="retention.finalized_attempt_data_deleted",
            resource_type="retention_batch",
            resource_id=str(uuid4()),
            details={"cutoff": cutoff.isoformat(), "approved_policy": approved_policy, **before},
        )
    )
    db.commit()
    return before


def _administrator_id(db: Session) -> str:
    actor_id = db.scalar(
        select(User.id)
        .join(user_roles, user_roles.c.user_id == User.id)
        .join(Role, Role.name == user_roles.c.role_name)
        .where(Role.name == "administrator")
        .order_by(User.created_at)
        .limit(1)
    )
    if not actor_id:
        raise RuntimeError("Retention requires an administrator account for audit attribution")
    return actor_id


def main() -> None:
    parser = argparse.ArgumentParser(description="Preview or purge expired finalized attempt data")
    parser.add_argument("--older-than-days", type=int, required=True)
    parser.add_argument("--apply", action="store_true", help="perform the deletion")
    parser.add_argument("--approved-policy", help="institution-approved policy reference")
    parser.add_argument("--confirm", action="store_true", help="confirm the deletion")
    args = parser.parse_args()
    if args.older_than_days < 1:
        parser.error("--older-than-days must be at least 1")
    if args.apply and (not args.approved_policy or not args.confirm):
        parser.error("--apply also requires --approved-policy and --confirm")

    cutoff = datetime.now(UTC) - timedelta(days=args.older_than_days)
    factory = get_session_factory()
    with factory() as db:
        if args.apply:
            result = purge_expired_attempt_data(
                db,
                cutoff,
                actor_id=_administrator_id(db),
                approved_policy=args.approved_policy,
            )
            print({"deleted": result, "cutoff": cutoff.isoformat()})
        else:
            print(
                {
                    "preview_only": True,
                    "eligible": preview_expired_attempt_data(db, cutoff),
                    "cutoff": cutoff.isoformat(),
                }
            )


if __name__ == "__main__":
    main()
