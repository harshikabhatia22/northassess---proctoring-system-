from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models import (
    Answer,
    AuditLog,
    Course,
    Exam,
    ExamAttempt,
    ProctoringConsent,
    ProctoringEvent,
    ProctoringSession,
    Question,
    ReviewDecision,
    Role,
    User,
)
from app.retention import preview_expired_attempt_data, purge_expired_attempt_data


def test_retention_preview_is_non_destructive_and_purge_is_audited():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    cutoff = datetime.now(UTC) - timedelta(days=30)
    now = datetime.now(UTC)
    with Session(engine) as db:
        admin_role, student_role = Role(name="administrator"), Role(name="student")
        admin = User(
            email="admin@example.test",
            display_name="Admin",
            password_hash="test-hash",
            roles=[admin_role],
        )
        student = User(
            email="student@example.test",
            display_name="Student",
            password_hash="test-hash",
            roles=[student_role],
        )
        db.add_all([admin, student])
        db.flush()
        course = Course(code="RET", name="Retention test", owner_id=admin.id)
        db.add(course)
        db.flush()
        exam = Exam(
            course_id=course.id,
            owner_id=admin.id,
            title="Old exam",
            opens_at=now - timedelta(days=60),
            closes_at=now - timedelta(days=59),
            duration_minutes=30,
            max_attempts=1,
        )
        db.add(exam)
        db.flush()
        question = Question(
            exam_id=exam.id,
            question_type="mcq",
            prompt="Question",
            options=[{"id": "a", "text": "A"}, {"id": "b", "text": "B"}],
            correct_option_id="a",
            marks=1,
            position=1,
        )
        attempt = ExamAttempt(
            exam_id=exam.id,
            student_id=student.id,
            attempt_number=1,
            status="submitted",
            started_at=now - timedelta(days=60),
            expires_at=now - timedelta(days=59),
            submitted_at=cutoff - timedelta(days=1),
            objective_score=1,
            objective_possible=1,
        )
        active_attempt = ExamAttempt(
            exam_id=exam.id,
            student_id=student.id,
            attempt_number=2,
            status="in_progress",
            started_at=now,
            expires_at=now + timedelta(minutes=30),
        )
        db.add_all([question, attempt, active_attempt])
        db.flush()
        active_attempt_id = active_attempt.id
        consent = ProctoringConsent(
            attempt_id=attempt.id,
            student_id=student.id,
            policy_version="test-v1",
            decision="accepted",
            decided_at=attempt.started_at,
            policy_sha256="0" * 64,
        )
        db.add(consent)
        db.flush()
        session = ProctoringSession(
            attempt_id=attempt.id,
            consent_id=consent.id,
            status="ended",
            camera_state="stopped",
            started_at=attempt.started_at,
            ended_at=attempt.submitted_at,
        )
        db.add(session)
        db.flush()
        event = ProctoringEvent(
            session_id=session.id,
            event_key="retention-test-event",
            event_kind="visible_behavior_observation",
            source="model",
            observed_at=attempt.submitted_at,
            payload={"detections": []},
        )
        db.add_all(
            [
                event,
                Answer(
                    attempt_id=attempt.id,
                    question_id=question.id,
                    response="a",
                    version=1,
                    saved_at=attempt.submitted_at,
                ),
            ]
        )
        db.flush()
        db.add(
            ReviewDecision(
                event_id=event.id,
                reviewer_id=admin.id,
                action="dismissed",
                notes="Test note",
                created_at=attempt.submitted_at,
            )
        )
        db.commit()

        preview = preview_expired_attempt_data(db, cutoff)
        assert preview == {
            "review_decisions": 1,
            "events": 1,
            "sessions": 1,
            "consents": 1,
            "answers": 1,
            "attempts": 1,
        }
        assert db.scalar(select(func.count()).select_from(ExamAttempt)) == 2

        deleted = purge_expired_attempt_data(
            db,
            cutoff,
            actor_id=admin.id,
            approved_policy="TEST-POLICY-1",
        )
        assert deleted == preview
        assert preview_expired_attempt_data(db, cutoff) == {
            "review_decisions": 0,
            "events": 0,
            "sessions": 0,
            "consents": 0,
            "answers": 0,
            "attempts": 0,
        }
        audit = db.scalar(select(AuditLog))
        assert audit is not None
        assert audit.action == "retention.finalized_attempt_data_deleted"
        assert audit.details["approved_policy"] == "TEST-POLICY-1"
        assert db.get(ExamAttempt, active_attempt_id).status == "in_progress"
    engine.dispose()
