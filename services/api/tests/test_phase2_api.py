import asyncio
import os
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import httpx
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import (
    AuditLog,
    Course,
    CourseMembership,
    Exam,
    ExamAssignment,
    ExamAttempt,
    ProctoringEvent,
    ProctoringSession,
    Question,
    Role,
    User,
)
from app.security import hash_password


def run_api_checks():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        db.add_all(
            [
                Role(name=name)
                for name in ("student", "instructor", "administrator", "ml_maintainer")
            ]
        )
        instructor_role, student_role, admin_role = (
            db.get(Role, "instructor"),
            db.get(Role, "student"),
            db.get(Role, "administrator"),
        )
        instructor = User(
            email="teacher@example.test",
            display_name="Taylor Teacher",
            password_hash=hash_password("a-long-test-password"),
            roles=[instructor_role],
        )
        student = User(
            email="learner@example.test",
            display_name="Sam Student",
            password_hash=hash_password("another-long-test-pass"),
            roles=[student_role],
        )
        administrator = User(
            email="admin@example.test",
            display_name="Alex Admin",
            password_hash=hash_password("a-third-long-test-password"),
            roles=[admin_role],
        )
        db.add_all([instructor, student, administrator])
        db.flush()
        course = Course(code="BIO 101", name="Biology", owner_id=instructor.id)
        db.add(course)
        db.flush()
        db.add(CourseMembership(course_id=course.id, student_id=student.id))
        exam = Exam(
            course_id=course.id,
            owner_id=instructor.id,
            title="Cell biology",
            instructions="Read carefully",
            status="published",
            opens_at=datetime.now(UTC) - timedelta(minutes=1),
            closes_at=datetime.now(UTC) + timedelta(hours=1),
            duration_minutes=30,
            max_attempts=2,
        )
        db.add(exam)
        db.flush()
        question = Question(
            exam_id=exam.id,
            question_type="mcq",
            prompt="Which is a cell?",
            options=[{"id": "a", "text": "Cell"}, {"id": "b", "text": "Rock"}],
            correct_option_id="a",
            marks=2,
            position=1,
        )
        db.add(question)
        db.add(ExamAssignment(exam_id=exam.id, student_id=student.id))
        db.commit()
        exam_id, question_id = exam.id, question.id

    def override_db():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db

    async def exercise():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            login = await client.post(
                "/api/v1/auth/login",
                json={"email": "learner@example.test", "password": "another-long-test-pass"},
                headers={"Origin": "http://localhost:5173"},
            )
            token = login.json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}
            frame_preflight = await client.options(
                "/api/v1/proctoring/sessions/test-session/frames",
                headers={
                    "Origin": "http://localhost:5173",
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "authorization,content-type,x-event-key",
                },
            )
            listed = await client.get("/api/v1/exams", headers=headers)
            attempt = await client.post(f"/api/v1/exams/{exam_id}/attempts", headers=headers)
            attempt_id = attempt.json()["id"]
            policy = await client.get("/api/v1/proctoring/policy", headers=headers)
            consent = await client.post(
                f"/api/v1/attempts/{attempt_id}/proctoring-consent",
                headers=headers,
                json={"policy_version": "proctoring-v2", "accept": True},
            )
            session_id = consent.json()["session"]["id"]
            with patch.dict(os.environ, {"VISION_SERVICE_URL": "", "VISION_INTERNAL_API_KEY": ""}):
                frame = await client.post(
                    f"/api/v1/proctoring/sessions/{session_id}/frames",
                    headers={
                        **headers,
                        "Content-Type": "image/jpeg",
                        "X-Event-Key": "sample-frame-1",
                    },
                    content=b"temporary-frame-payload",
                )

            class VisionResponse:
                @staticmethod
                def raise_for_status():
                    return None

                @staticmethod
                def json():
                    return {
                        "model_id": "test-model",
                        "processing_status": "ok",
                        "observation_semantics": "test visible signal",
                        "detections": [
                            {"class_name": "mobile_use", "score": 1.0, "box_xyxy": [0, 0, 1, 1]}
                        ],
                    }

            class VisionClient:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, *_args):
                    return None

                async def post(self, *_args, **_kwargs):
                    return VisionResponse()

            positive_frames = []
            with (
                patch.dict(
                    os.environ,
                    {"VISION_SERVICE_URL": "http://vision", "VISION_INTERNAL_API_KEY": "test-key"},
                ),
                patch("app.api.routes.platform.httpx.AsyncClient", return_value=VisionClient()),
            ):
                for frame_number in range(1, 4):
                    with factory() as db:
                        db.get(ProctoringSession, session_id).last_frame_at = None
                        db.commit()
                    positive_frames.append(
                        await client.post(
                            f"/api/v1/proctoring/sessions/{session_id}/frames",
                            headers={
                                **headers,
                                "Content-Type": "image/jpeg",
                                "X-Event-Key": f"positive-frame-{frame_number}",
                            },
                            content=b"synthetic-test-frame",
                        )
                    )
            with factory() as db:
                db.add(
                    ProctoringEvent(
                        session_id=session_id,
                        event_key="fixture-event-1",
                        event_kind="visible_behavior_observation",
                        source="model",
                        model_id="test-model",
                        payload={"detections": [{"class_name": "phone"}]},
                    )
                )
                db.commit()
            staff_login = await client.post(
                "/api/v1/auth/login",
                json={"email": "teacher@example.test", "password": "a-long-test-password"},
                headers={"Origin": "http://localhost:5173"},
            )
            staff_headers = {"Authorization": f"Bearer {staff_login.json()['access_token']}"}
            admin_login = await client.post(
                "/api/v1/auth/login",
                json={"email": "admin@example.test", "password": "a-third-long-test-password"},
                headers={"Origin": "http://localhost:5173"},
            )
            admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}
            events = await client.get(
                f"/api/v1/courses/{course.id}/proctoring-events", headers=staff_headers
            )
            decision = await client.post(
                f"/api/v1/proctoring-events/{events.json()[0]['id']}/review-decisions",
                headers=staff_headers,
                json={"action": "dismissed", "notes": "Reviewed as a non-issue."},
            )
            suspected_without_notes = await client.post(
                f"/api/v1/proctoring-events/{events.json()[0]['id']}/review-decisions",
                headers=staff_headers,
                json={"action": "suspected_cheating", "notes": ""},
            )
            suspected = await client.post(
                f"/api/v1/proctoring-events/{events.json()[0]['id']}/review-decisions",
                headers=staff_headers,
                json={
                    "action": "suspected_cheating",
                    "notes": "Human reviewer flagged this for academic-integrity review.",
                },
            )
            revoked = await client.post(
                f"/api/v1/proctoring/sessions/{session_id}/revoke", headers=headers
            )
            revoked_frame = await client.post(
                f"/api/v1/proctoring/sessions/{session_id}/frames",
                headers={
                    **headers,
                    "Content-Type": "image/jpeg",
                    "X-Event-Key": "sample-frame-2",
                },
                content=b"temporary-frame-payload",
            )
            saved = await client.put(
                f"/api/v1/attempts/{attempt_id}/answers/{question_id}",
                headers=headers,
                json={"response": "a", "expected_version": 0},
            )
            stale = await client.put(
                f"/api/v1/attempts/{attempt_id}/answers/{question_id}",
                headers=headers,
                json={"response": "b", "expected_version": 0},
            )
            submitted = await client.post(f"/api/v1/attempts/{attempt_id}/submit", headers=headers)
            second_attempt = await client.post(f"/api/v1/exams/{exam_id}/attempts", headers=headers)
            second_consent = await client.post(
                f"/api/v1/attempts/{second_attempt.json()['id']}/proctoring-consent",
                headers=headers,
                json={"policy_version": "proctoring-v2", "accept": True},
            )
            with factory() as db:
                expiring_attempt = db.get(ExamAttempt, second_attempt.json()["id"])
                expiring_attempt.expires_at = datetime.now(UTC) - timedelta(seconds=1)
                db.commit()
            expired_frame = await client.post(
                f"/api/v1/proctoring/sessions/{second_consent.json()['session']['id']}/frames",
                headers={
                    **headers,
                    "Content-Type": "image/jpeg",
                    "X-Event-Key": "expired-sample",
                },
                content=b"frame-after-deadline",
            )
            second_submit = await client.post(
                f"/api/v1/attempts/{second_attempt.json()['id']}/submit", headers=headers
            )
            with factory() as db:
                ended_on_submit = db.get(ProctoringSession, second_consent.json()["session"]["id"])
                ended_on_submit = bool(
                    ended_on_submit
                    and ended_on_submit.status == "ended"
                    and ended_on_submit.camera_state == "stopped"
                )
            analytics = await client.get(
                f"/api/v1/courses/{course.id}/analytics", headers=staff_headers
            )
            analytics_csv = await client.get(
                f"/api/v1/courses/{course.id}/analytics.csv", headers=staff_headers
            )
            student_analytics = await client.get(
                f"/api/v1/courses/{course.id}/analytics", headers=headers
            )
            admin_audit = await client.get("/api/v1/admin/audit-logs", headers=admin_headers)
            instructor_audit = await client.get("/api/v1/admin/audit-logs", headers=staff_headers)
            provisioned_student = await client.post(
                "/api/v1/users",
                headers=admin_headers,
                json={
                    "email": "new-learner@example.test",
                    "display_name": "New Learner",
                    "password": "a-fourth-long-test-password",
                    "role": "student",
                },
            )
            enrolled_by_email = await client.post(
                f"/api/v1/courses/{course.id}/students",
                headers=staff_headers,
                json={"student_email": "new-learner@example.test"},
            )
            roster = await client.get(
                f"/api/v1/courses/{course.id}/students", headers=staff_headers
            )
            return (
                login,
                listed,
                attempt,
                saved,
                stale,
                submitted,
                policy,
                consent,
                frame,
                positive_frames,
                events,
                decision,
                suspected_without_notes,
                suspected,
                revoked,
                revoked_frame,
                second_consent,
                second_submit,
                ended_on_submit,
                analytics,
                analytics_csv,
                student_analytics,
                frame_preflight,
                admin_audit,
                instructor_audit,
                expired_frame,
                provisioned_student,
                enrolled_by_email,
                roster,
            )

    try:
        results = asyncio.run(exercise())
        with factory() as session:
            audit_count = session.scalar(select(func.count()).select_from(AuditLog)) or 0
        return (*results, audit_count)
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_student_attempt_flow_hides_keys_saves_versioned_answers_and_scores():
    (
        login,
        listed,
        attempt,
        saved,
        stale,
        submitted,
        policy,
        consent,
        frame,
        positive_frames,
        events,
        decision,
        suspected_without_notes,
        suspected,
        revoked,
        revoked_frame,
        second_consent,
        second_submit,
        ended_on_submit,
        analytics,
        analytics_csv,
        student_analytics,
        frame_preflight,
        admin_audit,
        instructor_audit,
        expired_frame,
        provisioned_student,
        enrolled_by_email,
        roster,
        audit_count,
    ) = run_api_checks()

    assert login.status_code == 200
    assert listed.status_code == 200
    assert "correct_option_id" not in listed.json()[0]["questions"][0]
    assert attempt.status_code == 201
    assert saved.status_code == 200 and saved.json()["version"] == 1
    assert stale.status_code == 409
    assert submitted.status_code == 200
    assert submitted.json()["objective_score"] == 2
    assert submitted.json()["objective_possible"] == 2
    assert policy.status_code == 200 and policy.json()["raw_frames_retained"] is False
    assert consent.status_code == 201 and consent.json()["consent"] == "accepted"
    assert frame.status_code == 200 and frame.json()["attempt_continues"] is True
    assert frame.json()["warning_count"] == 0 and frame.json()["warning_threshold"] == 3
    assert [r.json()["warning_count"] for r in positive_frames] == [1, 2, 3]
    assert all(r.status_code == 200 and r.json()["attempt_continues"] for r in positive_frames)
    assert events.status_code == 200 and len(events.json()) == 4
    assert decision.status_code == 201 and decision.json()["action"] == "dismissed"
    assert suspected_without_notes.status_code == 422
    assert suspected.status_code == 201 and suspected.json()["action"] == "suspected_cheating"
    assert revoked.status_code == 200 and revoked.json()["consent"] == "revoked"
    assert revoked_frame.status_code == 409
    assert second_consent.status_code == 201
    assert second_submit.status_code == 200
    assert ended_on_submit is True
    assert analytics.status_code == 200
    assert analytics.json()["summary"]["finalized_attempts"] == 2
    assert analytics.json()["summary"]["completed_assignments"] == 1
    assert analytics.json()["summary"]["average_objective_percent"] is None
    assert analytics.json()["summary"]["score_suppressed"] is True
    assert analytics_csv.status_code == 200 and "Assessment" not in analytics_csv.text
    assert "learner@example.test" not in analytics_csv.text
    assert student_analytics.status_code == 403
    assert frame_preflight.status_code == 200
    assert "x-event-key" in frame_preflight.headers.get("access-control-allow-headers", "").lower()
    assert admin_audit.status_code == 200
    assert any(
        item["action"] == "course.analytics_exported" for item in admin_audit.json()["items"]
    )
    assert instructor_audit.status_code == 403
    assert expired_frame.status_code == 409
    assert provisioned_student.status_code == 201
    assert enrolled_by_email.status_code == 201 and enrolled_by_email.json()["enrolled"] is True
    assert any(user["email"] == "new-learner@example.test" for user in roster.json())
    assert audit_count >= 4
