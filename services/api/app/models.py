from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def new_id() -> str:
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC)


user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_name", ForeignKey("roles.name", ondelete="CASCADE"), primary_key=True),
)


class Role(Base):
    __tablename__ = "roles"

    name: Mapped[str] = mapped_column(String(40), primary_key=True)
    users: Mapped[list["User"]] = relationship(secondary=user_roles, back_populates="roles")


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(512))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    roles: Mapped[list[Role]] = relationship(
        secondary=user_roles, back_populates="users", lazy="selectin"
    )
    owned_courses: Mapped[list["Course"]] = relationship(back_populates="owner")


class RefreshSession(Base):
    __tablename__ = "refresh_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_by_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class BootstrapState(Base):
    __tablename__ = "bootstrap_state"
    __table_args__ = (CheckConstraint("id = 1", name="ck_single_bootstrap_state"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    initialized: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Course(Base):
    __tablename__ = "courses"
    __table_args__ = (UniqueConstraint("owner_id", "code", name="uq_course_owner_code"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(160))
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    owner: Mapped[User] = relationship(back_populates="owned_courses")
    memberships: Mapped[list["CourseMembership"]] = relationship(
        back_populates="course", cascade="all, delete-orphan"
    )
    exams: Mapped[list["Exam"]] = relationship(back_populates="course")


class CourseMembership(Base):
    __tablename__ = "course_memberships"
    __table_args__ = (UniqueConstraint("course_id", "student_id", name="uq_course_student"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    course: Mapped[Course] = relationship(back_populates="memberships")
    student: Mapped[User] = relationship()


class Exam(Base):
    __tablename__ = "exams"
    __table_args__ = (
        CheckConstraint("duration_minutes > 0", name="ck_exam_duration_positive"),
        CheckConstraint("max_attempts > 0", name="ck_exam_attempts_positive"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    course_id: Mapped[str] = mapped_column(
        ForeignKey("courses.id", ondelete="RESTRICT"), index=True
    )
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    instructions: Mapped[str] = mapped_column(String(5000), default="")
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    opens_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closes_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_minutes: Mapped[int] = mapped_column(Integer)
    max_attempts: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    course: Mapped[Course] = relationship(back_populates="exams")
    questions: Mapped[list["Question"]] = relationship(
        back_populates="exam", cascade="all, delete-orphan", order_by="Question.position"
    )
    assignments: Mapped[list["ExamAssignment"]] = relationship(
        back_populates="exam", cascade="all, delete-orphan"
    )


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (
        UniqueConstraint("exam_id", "position", name="uq_question_exam_position"),
        CheckConstraint("marks > 0", name="ck_question_marks_positive"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    exam_id: Mapped[str] = mapped_column(ForeignKey("exams.id", ondelete="CASCADE"), index=True)
    question_type: Mapped[str] = mapped_column(String(20))
    prompt: Mapped[str] = mapped_column(String(10000))
    options: Mapped[list[dict[str, str]] | None] = mapped_column(JSON, nullable=True)
    correct_option_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    marks: Mapped[int] = mapped_column(Integer)
    position: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    exam: Mapped[Exam] = relationship(back_populates="questions")


class ExamAssignment(Base):
    __tablename__ = "exam_assignments"
    __table_args__ = (UniqueConstraint("exam_id", "student_id", name="uq_exam_assignment_student"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    exam_id: Mapped[str] = mapped_column(ForeignKey("exams.id", ondelete="CASCADE"), index=True)
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    exam: Mapped[Exam] = relationship(back_populates="assignments")
    student: Mapped[User] = relationship()


class ExamAttempt(Base):
    __tablename__ = "exam_attempts"
    __table_args__ = (
        UniqueConstraint("exam_id", "student_id", "attempt_number", name="uq_attempt_number"),
        CheckConstraint("attempt_number > 0", name="ck_attempt_number_positive"),
        Index("ix_attempt_student_exam_status", "student_id", "exam_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    exam_id: Mapped[str] = mapped_column(ForeignKey("exams.id", ondelete="RESTRICT"), index=True)
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    attempt_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="in_progress", index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    objective_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    objective_possible: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exam: Mapped[Exam] = relationship()
    answers: Mapped[list["Answer"]] = relationship(
        back_populates="attempt", cascade="all, delete-orphan"
    )


class Answer(Base):
    __tablename__ = "answers"
    __table_args__ = (
        UniqueConstraint("attempt_id", "question_id", name="uq_answer_attempt_question"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    attempt_id: Mapped[str] = mapped_column(
        ForeignKey("exam_attempts.id", ondelete="CASCADE"), index=True
    )
    question_id: Mapped[str] = mapped_column(
        ForeignKey("questions.id", ondelete="RESTRICT"), index=True
    )
    response: Mapped[str | None] = mapped_column(String(10000), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    saved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    attempt: Mapped[ExamAttempt] = relationship(back_populates="answers")
    question: Mapped[Question] = relationship()


class ProctoringConsent(Base):
    __tablename__ = "proctoring_consents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    attempt_id: Mapped[str] = mapped_column(
        ForeignKey("exam_attempts.id", ondelete="CASCADE"), index=True
    )
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    policy_version: Mapped[str] = mapped_column(String(40))
    decision: Mapped[str] = mapped_column(String(20))
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    policy_sha256: Mapped[str] = mapped_column(String(64))


class ProctoringSession(Base):
    __tablename__ = "proctoring_sessions"
    __table_args__ = (UniqueConstraint("attempt_id", name="uq_proctoring_session_attempt"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    attempt_id: Mapped[str] = mapped_column(
        ForeignKey("exam_attempts.id", ondelete="CASCADE"), index=True
    )
    consent_id: Mapped[str] = mapped_column(
        ForeignKey("proctoring_consents.id", ondelete="RESTRICT"), unique=True
    )
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    camera_state: Mapped[str] = mapped_column(String(24), default="ready")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_frame_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProctoringEvent(Base):
    __tablename__ = "proctoring_events"
    __table_args__ = (
        UniqueConstraint("session_id", "event_key", name="uq_proctoring_event_idempotency"),
        Index("ix_proctoring_event_session_observed", "session_id", "observed_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("proctoring_sessions.id", ondelete="CASCADE"), index=True
    )
    event_key: Mapped[str] = mapped_column(String(80))
    event_kind: Mapped[str] = mapped_column(String(40))
    source: Mapped[str] = mapped_column(String(20), default="model")
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    model_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ReviewDecision(Base):
    __tablename__ = "review_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_id: Mapped[str] = mapped_column(
        ForeignKey("proctoring_events.id", ondelete="CASCADE"), index=True
    )
    reviewer_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    action: Mapped[str] = mapped_column(String(30))
    notes: Mapped[str] = mapped_column(String(2000), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    resource_type: Mapped[str] = mapped_column(String(40))
    resource_id: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
