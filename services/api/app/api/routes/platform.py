"""Phase 2 account, course, exam, and student attempt API."""

import csv
import hashlib
import io
import os
from datetime import UTC, datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.db.session import get_db
from app.models import (
    Answer,
    AuditLog,
    BootstrapState,
    Course,
    CourseMembership,
    Exam,
    ExamAssignment,
    ExamAttempt,
    ProctoringConsent,
    ProctoringEvent,
    ProctoringSession,
    Question,
    ReviewDecision,
    Role,
    User,
)
from app.security import (
    clear_refresh_cookie,
    create_refresh_session,
    current_user,
    find_refresh_session,
    hash_password,
    issue_access_token,
    require_csrf,
    require_roles,
    set_refresh_cookie,
    utc_aware,
    verify_origin,
    verify_password,
)

router = APIRouter()

PROCTORING_POLICY_VERSION = "proctoring-v2"
PROCTORING_POLICY_TEXT = (
    "Optional sampled camera analysis may report visible behavior annotations for human review. "
    "Three separate frames with one or more observations show an escalating student warning and "
    "make the signals available for instructor review. AI does not determine cheating, cancel "
    "the exam, or affect grades. No image frames are retained by this API. You may decline or "
    "revoke consent and continue through the no-camera route."
)
PROCTORING_POLICY_SHA256 = hashlib.sha256(PROCTORING_POLICY_TEXT.encode("utf-8")).hexdigest()
MAX_FRAME_BYTES = 4 * 1024 * 1024
MIN_FRAME_INTERVAL_SECONDS = 5
PROCTORING_REVIEW_WARNING_THRESHOLD = 3


def fail(code: int, detail: str) -> None:
    raise HTTPException(status_code=code, detail=detail)


def audit_action(
    db: Session,
    actor_id: str,
    action: str,
    resource_type: str,
    resource_id: str,
    details: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details or {},
        )
    )


def user_json(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "roles": sorted(role.name for role in user.roles),
        "is_active": user.is_active,
    }


def token_pair(db: Session, user: User, response: Response) -> dict:
    access, expires = issue_access_token(user.id)
    _, refresh, csrf = create_refresh_session(db, user.id)
    set_refresh_cookie(response, refresh)
    return {
        "access_token": access,
        "token_type": "bearer",
        "expires_in": expires,
        "csrf_token": csrf,
        "user": user_json(user),
    }


@router.post("/auth/bootstrap-admin", status_code=201)
def bootstrap_admin(db: Session = Depends(get_db)):
    settings = get_settings()
    if not settings.bootstrap_admin_email or not settings.bootstrap_admin_password:
        fail(404, "Administrator bootstrap is not configured")
    state = db.scalar(select(BootstrapState).where(BootstrapState.id == 1).with_for_update())
    if state is None:
        fail(503, "Database is not initialized; apply migrations first")
    if state.initialized:
        fail(409, "Administrator bootstrap has already been used")
    existing = db.scalar(select(User).where(User.email == settings.bootstrap_admin_email.lower()))
    if existing:
        state.initialized = True
        db.commit()
        fail(409, "Administrator account already exists; bootstrap disabled")
    admin_role = db.get(Role, "administrator")
    if admin_role is None:
        fail(503, "Roles are not initialized; apply migrations first")
    user = User(
        email=settings.bootstrap_admin_email.lower(),
        display_name="Platform administrator",
        password_hash=hash_password(settings.bootstrap_admin_password),
        roles=[admin_role],
    )
    state.initialized = True
    db.add(user)
    db.commit()
    return user_json(user)


@router.post("/auth/login")
def login(payload: dict, request: Request, response: Response, db: Session = Depends(get_db)):
    verify_origin(request)
    email = str(payload.get("email", "")).strip().lower()
    password = payload.get("password", "")
    user = db.scalar(select(User).options(selectinload(User.roles)).where(User.email == email))
    if (
        not user
        or not user.is_active
        or not isinstance(password, str)
        or not verify_password(password, user.password_hash)
    ):
        fail(401, "Email or password is incorrect")
    result = token_pair(db, user, response)
    db.commit()
    return result


@router.post("/auth/refresh")
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    verify_origin(request)
    raw = request.cookies.get("refresh_token")
    session = find_refresh_session(db, raw) if raw else None
    if not session or session.revoked_at or utc_aware(session.expires_at) <= datetime.now(UTC):
        clear_refresh_cookie(response)
        fail(401, "Refresh session is invalid or expired")
    require_csrf(request, session.csrf_hash)
    user = db.scalar(
        select(User).options(selectinload(User.roles)).where(User.id == session.user_id)
    )
    if not user or not user.is_active:
        session.revoked_at = datetime.now(UTC)
        db.commit()
        clear_refresh_cookie(response)
        fail(401, "Account is unavailable")
    session.revoked_at = datetime.now(UTC)
    result = token_pair(db, user, response)
    db.commit()
    return result


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    verify_origin(request)
    raw = request.cookies.get("refresh_token")
    session = find_refresh_session(db, raw) if raw else None
    if session and not session.revoked_at:
        require_csrf(request, session.csrf_hash)
        session.revoked_at = datetime.now(UTC)
        db.commit()
    clear_refresh_cookie(response)


@router.get("/auth/me")
def me(user: User = Depends(current_user)):
    return user_json(user)


@router.get("/users")
def list_users(db: Session = Depends(get_db), _: User = Depends(require_roles("administrator"))):
    users = db.scalars(select(User).options(selectinload(User.roles)).order_by(User.email)).all()
    return [user_json(user) for user in users]


@router.get("/admin/audit-logs")
def list_audit_logs(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10000),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("administrator")),
):
    rows = db.execute(
        select(AuditLog, User.email)
        .join(User, User.id == AuditLog.actor_id)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return {
        "items": [
            {
                "id": entry.id,
                "actor_email": email,
                "action": entry.action,
                "resource_type": entry.resource_type,
                "resource_id": entry.resource_id,
                "created_at": entry.created_at,
                "details": entry.details,
            }
            for entry, email in rows
        ],
        "limit": limit,
        "offset": offset,
    }


@router.post("/users", status_code=201)
def create_user(
    payload: dict,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles("administrator")),
):
    email = str(payload.get("email", "")).strip().lower()
    name = str(payload.get("display_name", "")).strip()
    password = payload.get("password")
    role_name = payload.get("role")
    if "@" not in email or len(email) > 320 or not name or len(name) > 120:
        fail(422, "Valid email and display name are required")
    if not isinstance(password, str) or len(password) < 12:
        fail(422, "Password must contain at least 12 characters")
    if role_name not in {"student", "instructor", "ml_maintainer"}:
        fail(422, "Role must be student, instructor, or ml_maintainer")
    if db.scalar(select(User.id).where(User.email == email)):
        fail(409, "Email is already registered")
    role = db.get(Role, role_name)
    user = User(email=email, display_name=name, password_hash=hash_password(password), roles=[role])
    db.add(user)
    db.flush()
    audit_action(db, admin.id, "user.created", "user", user.id, {"role": role_name})
    db.commit()
    db.refresh(user)
    return user_json(user)


def course_visible(db: Session, course_id: str, user: User) -> Course:
    course = db.get(Course, course_id)
    if not course:
        fail(404, "Course not found")
    if (
        "administrator" not in {r.name for r in user.roles}
        and course.owner_id != user.id
        and db.scalar(
            select(CourseMembership.id).where(
                CourseMembership.course_id == course_id, CourseMembership.student_id == user.id
            )
        )
        is None
    ):
        fail(404, "Course not found")
    return course


@router.get("/courses")
def list_courses(db: Session = Depends(get_db), user: User = Depends(current_user)):
    roles = {r.name for r in user.roles}
    if roles.intersection({"administrator", "instructor"}):
        query = (
            select(Course)
            if "administrator" in roles
            else select(Course).where(Course.owner_id == user.id)
        )
    else:
        query = select(Course).join(CourseMembership).where(CourseMembership.student_id == user.id)
    return [
        {"id": c.id, "code": c.code, "name": c.name, "owner_id": c.owner_id}
        for c in db.scalars(query.order_by(Course.name)).all()
    ]


@router.post("/courses", status_code=201)
def create_course(
    payload: dict,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("instructor", "administrator")),
):
    code, name = str(payload.get("code", "")).strip().upper(), str(payload.get("name", "")).strip()
    if not code or len(code) > 32 or not name or len(name) > 160:
        fail(422, "Course code and name are required")
    course = Course(code=code, name=name, owner_id=user.id)
    db.add(course)
    db.flush()
    audit_action(db, user.id, "course.created", "course", course.id, {"code": code})
    db.commit()
    db.refresh(course)
    return {"id": course.id, "code": course.code, "name": course.name, "owner_id": course.owner_id}


@router.post("/courses/{course_id}/students", status_code=201)
def enroll_student(
    course_id: str,
    payload: dict,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("instructor", "administrator")),
):
    course = course_visible(db, course_id, user)
    student_id = payload.get("student_id")
    student_email = str(payload.get("student_email", "")).strip().lower()
    if student_email:
        student_query = (
            select(User).options(selectinload(User.roles)).where(User.email == student_email)
        )
    elif student_id:
        student_query = select(User).options(selectinload(User.roles)).where(User.id == student_id)
    else:
        fail(422, "Provide a student email address")
    student = db.scalar(student_query)
    if not student or "student" not in {r.name for r in student.roles}:
        fail(404, "Student account not found")
    membership = db.scalar(
        select(CourseMembership).where(
            CourseMembership.course_id == course.id, CourseMembership.student_id == student.id
        )
    )
    if not membership:
        membership = CourseMembership(course_id=course.id, student_id=student.id)
        db.add(membership)
        db.flush()
        audit_action(
            db,
            user.id,
            "course.student_enrolled",
            "course_membership",
            membership.id,
            {"course_id": course.id},
        )
        db.commit()
    return {"course_id": course.id, "student_id": student.id, "enrolled": True}


@router.get("/courses/{course_id}/students")
def course_roster(
    course_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    course = course_visible(db, course_id, user)
    if course.owner_id != user.id and "administrator" not in {r.name for r in user.roles}:
        fail(403, "Only course staff can view the roster")
    users = db.scalars(
        select(User)
        .join(CourseMembership)
        .where(CourseMembership.course_id == course.id)
        .options(selectinload(User.roles))
    ).all()
    return [user_json(student) for student in users]


def exam_json(exam: Exam, include_key: bool = False) -> dict:
    return {
        "id": exam.id,
        "course_id": exam.course_id,
        "title": exam.title,
        "instructions": exam.instructions,
        "status": exam.status,
        "opens_at": exam.opens_at,
        "closes_at": exam.closes_at,
        "duration_minutes": exam.duration_minutes,
        "max_attempts": exam.max_attempts,
        "questions": [question_json(q, include_key) for q in exam.questions],
    }


def question_json(q: Question, include_key: bool = False) -> dict:
    data = {
        "id": q.id,
        "question_type": q.question_type,
        "prompt": q.prompt,
        "options": q.options,
        "marks": q.marks,
        "position": q.position,
    }
    if include_key:
        data["correct_option_id"] = q.correct_option_id
    return data


def owned_exam(db: Session, exam_id: str, user: User) -> Exam:
    exam = db.scalar(select(Exam).options(selectinload(Exam.questions)).where(Exam.id == exam_id))
    if not exam:
        fail(404, "Exam not found")
    if exam.owner_id != user.id and "administrator" not in {r.name for r in user.roles}:
        fail(404, "Exam not found")
    return exam


@router.get("/exams")
def list_exams(db: Session = Depends(get_db), user: User = Depends(current_user)):
    roles = {r.name for r in user.roles}
    query = select(Exam).options(selectinload(Exam.questions))
    if "administrator" not in roles:
        if "instructor" in roles:
            query = query.where(Exam.owner_id == user.id)
        else:
            query = query.join(ExamAssignment).where(
                ExamAssignment.student_id == user.id, Exam.status == "published"
            )
    return [
        exam_json(e, include_key="instructor" in roles or "administrator" in roles)
        for e in db.scalars(query.order_by(Exam.opens_at)).unique().all()
    ]


@router.post("/exams", status_code=201)
def create_exam(
    payload: dict,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("instructor", "administrator")),
):
    course = course_visible(db, payload.get("course_id", ""), user)
    opens = datetime.fromisoformat(str(payload.get("opens_at", "")))
    closes = datetime.fromisoformat(str(payload.get("closes_at", "")))
    duration, attempts = (
        int(payload.get("duration_minutes", 0)),
        int(payload.get("max_attempts", 1)),
    )
    title = str(payload.get("title", "")).strip()
    if (
        not title
        or len(title) > 200
        or utc_aware(closes) <= utc_aware(opens)
        or duration < 1
        or attempts < 1
    ):
        fail(422, "Provide a title, valid exam window, positive duration, and attempt limit")
    exam = Exam(
        course_id=course.id,
        owner_id=user.id,
        title=title,
        instructions=str(payload.get("instructions", ""))[:5000],
        opens_at=opens,
        closes_at=closes,
        duration_minutes=duration,
        max_attempts=attempts,
    )
    db.add(exam)
    db.commit()
    db.refresh(exam)
    return exam_json(exam, True)


@router.post("/exams/{exam_id}/questions", status_code=201)
def add_question(
    exam_id: str,
    payload: dict,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("instructor", "administrator")),
):
    exam = owned_exam(db, exam_id, user)
    if exam.status != "draft":
        fail(409, "Questions can only be changed while the exam is a draft")
    kind, prompt, marks = (
        payload.get("question_type"),
        str(payload.get("prompt", "")).strip(),
        int(payload.get("marks", 1)),
    )
    options, correct = payload.get("options"), payload.get("correct_option_id")
    if kind not in {"mcq", "descriptive"} or not prompt or len(prompt) > 10000 or marks < 1:
        fail(422, "Question type, prompt, and positive marks are required")
    if kind == "mcq":
        if (
            not isinstance(options, list)
            or len(options) < 2
            or not all(isinstance(x, dict) and x.get("id") and x.get("text") for x in options)
            or correct not in {x["id"] for x in options}
        ):
            fail(422, "Multiple choice questions need options and a valid correct option")
    else:
        options, correct = None, None
    question = Question(
        exam_id=exam.id,
        question_type=kind,
        prompt=prompt,
        options=options,
        correct_option_id=correct,
        marks=marks,
        position=len(exam.questions) + 1,
    )
    db.add(question)
    db.commit()
    db.refresh(question)
    return question_json(question, True)


@router.post("/exams/{exam_id}/publish")
def publish_exam(
    exam_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("instructor", "administrator")),
):
    exam = owned_exam(db, exam_id, user)
    if exam.status != "draft" or not exam.questions:
        fail(409, "Only a draft exam with at least one question can be published")
    members = db.scalars(
        select(CourseMembership).where(CourseMembership.course_id == exam.course_id)
    ).all()
    if not members:
        fail(409, "Enroll at least one student before publishing")
    exam.status = "published"
    for membership in members:
        db.add(ExamAssignment(exam_id=exam.id, student_id=membership.student_id))
    audit_action(db, user.id, "exam.published", "exam", exam.id, {"assignment_count": len(members)})
    db.commit()
    return exam_json(exam, True)


def get_attempt(db: Session, attempt_id: str, user: User) -> ExamAttempt:
    attempt = db.scalar(
        select(ExamAttempt)
        .options(
            selectinload(ExamAttempt.answers).selectinload(Answer.question),
            selectinload(ExamAttempt.exam).selectinload(Exam.questions),
        )
        .where(ExamAttempt.id == attempt_id)
    )
    if not attempt or attempt.student_id != user.id:
        fail(404, "Attempt not found")
    return attempt


def attempt_json(attempt: ExamAttempt) -> dict:
    return {
        "id": attempt.id,
        "exam_id": attempt.exam_id,
        "status": attempt.status,
        "attempt_number": attempt.attempt_number,
        "started_at": attempt.started_at,
        "expires_at": attempt.expires_at,
        "submitted_at": attempt.submitted_at,
        "objective_score": attempt.objective_score,
        "objective_possible": attempt.objective_possible,
        "exam": {
            **exam_json(attempt.exam),
            "questions": [question_json(q) for q in attempt.exam.questions],
        },
        "answers": [
            {
                "question_id": a.question_id,
                "response": a.response,
                "version": a.version,
                "saved_at": a.saved_at,
            }
            for a in attempt.answers
        ],
    }


@router.post("/exams/{exam_id}/attempts", status_code=201)
def start_attempt(
    exam_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("student"))
):
    exam = db.scalar(
        select(Exam)
        .options(selectinload(Exam.questions))
        .where(Exam.id == exam_id, Exam.status == "published")
    )
    if not exam or not db.scalar(
        select(ExamAssignment.id).where(
            ExamAssignment.exam_id == exam_id, ExamAssignment.student_id == user.id
        )
    ):
        fail(404, "Assigned exam not found")
    existing = db.scalar(
        select(ExamAttempt).where(
            ExamAttempt.exam_id == exam.id,
            ExamAttempt.student_id == user.id,
            ExamAttempt.status == "in_progress",
        )
    )
    if existing:
        return attempt_json(get_attempt(db, existing.id, user))
    now = datetime.now(UTC)
    if now < utc_aware(exam.opens_at) or now >= utc_aware(exam.closes_at):
        fail(409, "Exam is outside its availability window")
    count = (
        db.scalar(
            select(func.count())
            .select_from(ExamAttempt)
            .where(ExamAttempt.exam_id == exam.id, ExamAttempt.student_id == user.id)
        )
        or 0
    )
    if count >= exam.max_attempts:
        fail(409, "Maximum attempts reached")
    deadline = min(now + timedelta(minutes=exam.duration_minutes), utc_aware(exam.closes_at))
    attempt = ExamAttempt(
        exam_id=exam.id,
        student_id=user.id,
        attempt_number=count + 1,
        started_at=now,
        expires_at=deadline,
    )
    db.add(attempt)
    db.flush()
    audit_action(db, user.id, "attempt.started", "exam_attempt", attempt.id, {"exam_id": exam.id})
    db.commit()
    return attempt_json(get_attempt(db, attempt.id, user))


@router.get("/attempts/{attempt_id}")
def read_attempt(
    attempt_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("student"))
):
    return attempt_json(get_attempt(db, attempt_id, user))


@router.put("/attempts/{attempt_id}/answers/{question_id}")
def save_answer(
    attempt_id: str,
    question_id: str,
    payload: dict,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("student")),
):
    attempt = get_attempt(db, attempt_id, user)
    now = datetime.now(UTC)
    if attempt.status != "in_progress" or now >= utc_aware(attempt.expires_at):
        fail(409, "Attempt is no longer accepting answers")
    question = next((q for q in attempt.exam.questions if q.id == question_id), None)
    if not question:
        fail(404, "Question not found for this attempt")
    response_value = payload.get("response")
    if response_value is not None and (
        not isinstance(response_value, str) or len(response_value) > 10000
    ):
        fail(422, "Answer must be text no longer than 10,000 characters")
    if (
        question.question_type == "mcq"
        and response_value is not None
        and response_value not in {o["id"] for o in question.options}
    ):
        fail(422, "Choose one of the available options")
    answer = db.scalar(
        select(Answer).where(Answer.attempt_id == attempt.id, Answer.question_id == question.id)
    )
    expected = payload.get("expected_version", 0)
    if (answer.version if answer else 0) != expected:
        fail(409, "Answer changed in another request; reload the attempt")
    if answer:
        answer.response, answer.version, answer.saved_at = response_value, answer.version + 1, now
    else:
        answer = Answer(
            attempt_id=attempt.id,
            question_id=question.id,
            response=response_value,
            version=1,
            saved_at=now,
        )
        db.add(answer)
    db.commit()
    return {
        "question_id": answer.question_id,
        "response": answer.response,
        "version": answer.version,
        "saved_at": answer.saved_at,
    }


@router.post("/attempts/{attempt_id}/submit")
def submit_attempt(
    attempt_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("student"))
):
    attempt = get_attempt(db, attempt_id, user)
    if attempt.status != "in_progress":
        return attempt_json(attempt)
    questions = attempt.exam.questions
    by_question = {a.question_id: a for a in attempt.answers}
    score = sum(
        q.marks
        for q in questions
        if q.question_type == "mcq"
        and q.id in by_question
        and by_question[q.id].response == q.correct_option_id
    )
    possible = sum(q.marks for q in questions if q.question_type == "mcq")
    attempt.status = (
        "expired" if datetime.now(UTC) >= utc_aware(attempt.expires_at) else "submitted"
    )
    attempt.submitted_at = datetime.now(UTC)
    attempt.objective_score, attempt.objective_possible = score, possible
    active_session = db.scalar(
        select(ProctoringSession).where(
            ProctoringSession.attempt_id == attempt.id,
            ProctoringSession.status == "active",
        )
    )
    if active_session:
        consent = db.get(ProctoringConsent, active_session.consent_id)
        if consent and consent.revoked_at is None:
            consent.revoked_at = attempt.submitted_at
        active_session.status = "ended"
        active_session.camera_state = "stopped"
        active_session.ended_at = attempt.submitted_at
    audit_action(
        db,
        user.id,
        "attempt.submitted",
        "exam_attempt",
        attempt.id,
        {"status": attempt.status},
    )
    db.commit()
    return attempt_json(get_attempt(db, attempt.id, user))


def proctoring_session_json(session: ProctoringSession) -> dict:
    return {
        "id": session.id,
        "attempt_id": session.attempt_id,
        "status": session.status,
        "camera_state": session.camera_state,
        "started_at": session.started_at,
        "ended_at": session.ended_at,
    }


def can_review_course(course: Course, user: User) -> bool:
    roles = {role.name for role in user.roles}
    return "administrator" in roles or ("instructor" in roles and course.owner_id == user.id)


@router.get("/proctoring/policy")
def get_proctoring_policy(user: User = Depends(require_roles("student"))):
    return {
        "version": PROCTORING_POLICY_VERSION,
        "text": PROCTORING_POLICY_TEXT,
        "sha256": PROCTORING_POLICY_SHA256,
        "sampling_interval_seconds": MIN_FRAME_INTERVAL_SECONDS,
        "raw_frames_retained": False,
        "declining_consent_blocks_exam": False,
    }


@router.post("/attempts/{attempt_id}/proctoring-consent", status_code=201)
def record_proctoring_consent(
    attempt_id: str,
    payload: dict,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("student")),
):
    attempt = get_attempt(db, attempt_id, user)
    if attempt.status != "in_progress" or datetime.now(UTC) >= utc_aware(attempt.expires_at):
        fail(409, "Proctoring consent is available only during an active attempt")
    if payload.get("policy_version") != PROCTORING_POLICY_VERSION:
        fail(409, "The consent policy changed; reload the policy before choosing")
    accepted = payload.get("accept")
    if not isinstance(accepted, bool):
        fail(422, "Consent decision must be true or false")
    existing_session = db.scalar(
        select(ProctoringSession).where(ProctoringSession.attempt_id == attempt.id)
    )
    if existing_session:
        if existing_session.status == "active" and accepted:
            audit_action(
                db,
                user.id,
                "proctoring.consent_reaffirmed",
                "proctoring_session",
                existing_session.id,
            )
            db.commit()
            return {"consent": "accepted", "session": proctoring_session_json(existing_session)}
        if existing_session.status == "active" and not accepted:
            consent = db.get(ProctoringConsent, existing_session.consent_id)
            consent.revoked_at = datetime.now(UTC)
            existing_session.status = "ended"
            existing_session.camera_state = "stopped"
            existing_session.ended_at = datetime.now(UTC)
            audit_action(
                db, user.id, "proctoring.consent_revoked", "proctoring_session", existing_session.id
            )
            db.commit()
            return {"consent": "declined", "session": None, "alternative_route": True}
        fail(409, "Proctoring session has already ended for this attempt")
    now = datetime.now(UTC)
    consent = ProctoringConsent(
        attempt_id=attempt.id,
        student_id=user.id,
        policy_version=PROCTORING_POLICY_VERSION,
        decision="accepted" if accepted else "declined",
        decided_at=now,
        policy_sha256=PROCTORING_POLICY_SHA256,
    )
    db.add(consent)
    db.flush()
    if not accepted:
        audit_action(db, user.id, "proctoring.consent_declined", "proctoring_consent", consent.id)
        db.commit()
        return {"consent": "declined", "session": None, "alternative_route": True}
    session = ProctoringSession(
        attempt_id=attempt.id,
        consent_id=consent.id,
        camera_state="ready",
        started_at=now,
    )
    db.add(session)
    db.flush()
    audit_action(db, user.id, "proctoring.consent_accepted", "proctoring_session", session.id)
    db.commit()
    db.refresh(session)
    return {"consent": "accepted", "session": proctoring_session_json(session)}


@router.post("/proctoring/sessions/{session_id}/revoke")
def revoke_proctoring_consent(
    session_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("student")),
):
    session = db.get(ProctoringSession, session_id)
    if not session:
        fail(404, "Proctoring session not found")
    get_attempt(db, session.attempt_id, user)
    consent = db.get(ProctoringConsent, session.consent_id)
    if consent.revoked_at is None:
        consent.revoked_at = datetime.now(UTC)
    session.status = "ended"
    session.camera_state = "stopped"
    session.ended_at = datetime.now(UTC)
    audit_action(db, user.id, "proctoring.consent_revoked", "proctoring_session", session.id)
    db.commit()
    return {"consent": "revoked", "session": proctoring_session_json(session)}


@router.post("/proctoring/sessions/{session_id}/frames")
async def submit_proctoring_frame(
    session_id: str,
    request: Request,
    x_event_key: str = Header(default="", alias="X-Event-Key"),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("student")),
):
    session = db.get(ProctoringSession, session_id)
    if not session:
        fail(404, "Proctoring session not found")
    attempt = get_attempt(db, session.attempt_id, user)
    consent = db.get(ProctoringConsent, session.consent_id)
    now = datetime.now(UTC)
    if (
        session.status != "active"
        or consent.decision != "accepted"
        or consent.revoked_at is not None
        or attempt.status != "in_progress"
        or now >= utc_aware(attempt.expires_at)
    ):
        fail(409, "Proctoring consent or exam session is no longer active")
    if (
        session.last_frame_at
        and (now - utc_aware(session.last_frame_at)).total_seconds() < MIN_FRAME_INTERVAL_SECONDS
    ):
        fail(429, "Wait before submitting another sampled frame")
    media_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
    if media_type not in {"image/jpeg", "image/png"}:
        fail(415, "Frame must be image/jpeg or image/png")
    if not x_event_key or len(x_event_key) > 80:
        fail(422, "X-Event-Key is required and must be at most 80 characters")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_FRAME_BYTES:
            fail(413, "Frame exceeds the 4 MiB limit")
        chunks.append(chunk)
    frame = b"".join(chunks)
    if not frame:
        fail(400, "Frame body is empty")

    service_url = os.environ.get("VISION_SERVICE_URL", "").rstrip("/")
    service_key = os.environ.get("VISION_INTERNAL_API_KEY", "")
    session.last_frame_at = now
    session.camera_state = "processing"
    db.commit()
    if not service_url or not service_key:
        session.camera_state = "inference_unavailable"
        db.commit()
        warning_count = (
            db.scalar(
                select(func.count())
                .select_from(ProctoringEvent)
                .where(ProctoringEvent.session_id == session.id)
            )
            or 0
        )
        return {
            "processing_status": "inference_unavailable",
            "attempt_continues": True,
            "warning_count": warning_count,
            "warning_threshold": PROCTORING_REVIEW_WARNING_THRESHOLD,
        }
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            response = await client.post(
                f"{service_url}/api/v1/detect",
                content=frame,
                headers={
                    "Content-Type": media_type,
                    "X-Internal-API-Key": service_key,
                },
            )
        response.raise_for_status()
        result = response.json()
    except (httpx.HTTPError, ValueError):
        current_session = db.scalar(
            select(ProctoringSession)
            .where(ProctoringSession.id == session.id)
            .execution_options(populate_existing=True)
        )
        if current_session and current_session.status == "active":
            current_session.camera_state = "inference_unavailable"
        db.commit()
        return {"processing_status": "inference_unavailable", "attempt_continues": True}

    # Re-check after network inference: consent may have been revoked, or the
    # attempt submitted, while the private vision service was processing.
    current_session = db.scalar(
        select(ProctoringSession)
        .where(ProctoringSession.id == session.id)
        .execution_options(populate_existing=True)
    )
    current_attempt = db.get(ExamAttempt, attempt.id, populate_existing=True)
    current_consent = db.get(ProctoringConsent, consent.id, populate_existing=True)
    if (
        not current_session
        or current_session.status != "active"
        or not current_attempt
        or current_attempt.status != "in_progress"
        or not current_consent
        or current_consent.revoked_at is not None
    ):
        return {
            "processing_status": "discarded_session_ended",
            "observation_count": 0,
            "event_id": None,
            "attempt_continues": current_attempt.status == "in_progress",
        }
    current_session.camera_state = "ready"
    detections = result.get("detections", [])
    event = None
    if detections:
        event = db.scalar(
            select(ProctoringEvent).where(
                ProctoringEvent.session_id == current_session.id,
                ProctoringEvent.event_key == x_event_key,
            )
        )
        if event is None:
            event = ProctoringEvent(
                session_id=current_session.id,
                event_key=x_event_key,
                event_kind="visible_behavior_observation",
                source="model",
                observed_at=now,
                model_id=result.get("model_id"),
                payload={
                    "observation_semantics": result.get("observation_semantics"),
                    "detections": detections,
                    "inference_latency_ms": result.get("inference_latency_ms"),
                },
            )
            db.add(event)
    db.commit()
    warning_count = (
        db.scalar(
            select(func.count())
            .select_from(ProctoringEvent)
            .where(ProctoringEvent.session_id == current_session.id)
        )
        or 0
    )
    return {
        "processing_status": result.get("processing_status", "ok"),
        "observation_count": len(detections),
        "event_id": event.id if event else None,
        "warning_count": warning_count,
        "warning_threshold": PROCTORING_REVIEW_WARNING_THRESHOLD,
        "attempt_continues": True,
    }


@router.post("/proctoring/sessions/{session_id}/end")
def end_proctoring_session(
    session_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("student")),
):
    session = db.get(ProctoringSession, session_id)
    if not session:
        fail(404, "Proctoring session not found")
    get_attempt(db, session.attempt_id, user)
    session.status = "ended"
    session.camera_state = "stopped"
    session.ended_at = datetime.now(UTC)
    db.commit()
    return proctoring_session_json(session)


@router.get("/courses/{course_id}/proctoring-events")
def list_proctoring_events(
    course_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("instructor", "administrator")),
):
    course = db.get(Course, course_id)
    if not course or not can_review_course(course, user):
        fail(404, "Course not found")
    events = db.scalars(
        select(ProctoringEvent)
        .join(ProctoringSession, ProctoringEvent.session_id == ProctoringSession.id)
        .join(ExamAttempt, ProctoringSession.attempt_id == ExamAttempt.id)
        .join(Exam, ExamAttempt.exam_id == Exam.id)
        .where(Exam.course_id == course.id)
        .order_by(ProctoringEvent.observed_at.desc())
        .limit(100)
    ).all()
    audit_action(db, user.id, "proctoring.events_read", "course", course.id, {"count": len(events)})
    event_ids = [event.id for event in events]
    decisions = (
        db.scalars(
            select(ReviewDecision)
            .where(ReviewDecision.event_id.in_(event_ids))
            .order_by(ReviewDecision.created_at)
        ).all()
        if event_ids
        else []
    )
    decisions_by_event: dict[str, list[dict]] = {}
    for decision in decisions:
        decisions_by_event.setdefault(decision.event_id, []).append(
            {
                "action": decision.action,
                "notes": decision.notes,
                "reviewer_id": decision.reviewer_id,
                "created_at": decision.created_at,
            }
        )
    db.commit()
    return [
        {
            "id": event.id,
            "event_kind": event.event_kind,
            "source": event.source,
            "observed_at": event.observed_at,
            "model_id": event.model_id,
            "payload": event.payload,
            "decisions": decisions_by_event.get(event.id, []),
        }
        for event in events
    ]


@router.post("/proctoring-events/{event_id}/review-decisions", status_code=201)
def create_review_decision(
    event_id: str,
    payload: dict,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("instructor", "administrator")),
):
    event = db.get(ProctoringEvent, event_id)
    if not event:
        fail(404, "Observation not found")
    session = db.get(ProctoringSession, event.session_id)
    attempt = db.get(ExamAttempt, session.attempt_id)
    exam = db.get(Exam, attempt.exam_id)
    course = db.get(Course, exam.course_id)
    if not can_review_course(course, user):
        fail(404, "Observation not found")
    action = payload.get("action")
    notes = payload.get("notes", "")
    if action not in {"reviewed", "dismissed", "needs_follow_up", "suspected_cheating"}:
        fail(422, "Choose a supported review action")
    if not isinstance(notes, str) or len(notes) > 2000:
        fail(422, "Review notes must be text up to 2,000 characters")
    if action == "suspected_cheating" and not notes.strip():
        fail(422, "Add a human reviewer note before recording suspected cheating")
    decision = ReviewDecision(
        event_id=event.id,
        reviewer_id=user.id,
        action=action,
        notes=notes,
    )
    db.add(decision)
    audit_action(
        db,
        user.id,
        "proctoring.review_decision_created",
        "proctoring_event",
        event.id,
        {"action": action},
    )
    db.commit()
    return {
        "id": decision.id,
        "event_id": decision.event_id,
        "action": decision.action,
        "notes": decision.notes,
        "created_at": decision.created_at,
    }


def _course_analytics(db: Session, course: Course) -> dict:
    exams = db.scalars(
        select(Exam).where(Exam.course_id == course.id).order_by(Exam.created_at.desc())
    ).all()
    assignments = db.scalars(
        select(ExamAssignment)
        .join(Exam, ExamAssignment.exam_id == Exam.id)
        .where(Exam.course_id == course.id)
    ).all()
    attempts = db.scalars(
        select(ExamAttempt)
        .join(Exam, ExamAttempt.exam_id == Exam.id)
        .where(Exam.course_id == course.id)
    ).all()

    assignments_by_exam: dict[str, set[str]] = {}
    for assignment in assignments:
        assignments_by_exam.setdefault(assignment.exam_id, set()).add(assignment.student_id)
    attempts_by_exam: dict[str, list[ExamAttempt]] = {}
    for attempt in attempts:
        attempts_by_exam.setdefault(attempt.exam_id, []).append(attempt)

    exam_rows = []
    total_assigned = 0
    total_completed_assignments = 0
    total_objective_score = 0
    total_objective_possible = 0
    scored_attempt_count = 0
    final_attempts = []
    for exam in exams:
        assigned_students = assignments_by_exam.get(exam.id, set())
        exam_attempts = attempts_by_exam.get(exam.id, [])
        completed_attempts = [a for a in exam_attempts if a.status in {"submitted", "expired"}]
        completed_students = {a.student_id for a in completed_attempts}
        scored_attempts = [
            a
            for a in completed_attempts
            if a.objective_score is not None
            and a.objective_possible is not None
            and a.objective_possible > 0
        ]
        score = sum(a.objective_score or 0 for a in scored_attempts)
        possible = sum(a.objective_possible or 0 for a in scored_attempts)
        score_suppressed = len(scored_attempts) < 5
        total_assigned += len(assigned_students)
        total_completed_assignments += len(completed_students & assigned_students)
        total_objective_score += score
        total_objective_possible += possible
        scored_attempt_count += len(scored_attempts)
        final_attempts.extend(completed_attempts)
        exam_rows.append(
            {
                "id": exam.id,
                "title": exam.title,
                "status": exam.status,
                "assigned_students": len(assigned_students),
                "started_attempts": len(exam_attempts),
                "completed_attempts": len(completed_attempts),
                "in_progress_attempts": sum(a.status == "in_progress" for a in exam_attempts),
                "completed_students": len(completed_students & assigned_students),
                "completion_percent": round(
                    100 * len(completed_students & assigned_students) / len(assigned_students), 1
                )
                if assigned_students
                else None,
                "average_objective_percent": round(100 * score / possible, 1)
                if possible and not score_suppressed
                else None,
                "score_suppressed": score_suppressed,
            }
        )

    today = datetime.now(UTC).date()
    daily = {(today - timedelta(days=offset)).isoformat(): 0 for offset in range(13, -1, -1)}
    for attempt in final_attempts:
        if attempt.submitted_at:
            day = utc_aware(attempt.submitted_at).date().isoformat()
            if day in daily:
                daily[day] += 1

    return {
        "course": {"id": course.id, "code": course.code, "name": course.name},
        "generated_at": datetime.now(UTC),
        "summary": {
            "exam_count": len(exams),
            "published_exam_count": sum(exam.status == "published" for exam in exams),
            "assigned_students": total_assigned,
            "completed_assignments": total_completed_assignments,
            "completion_percent": round(100 * total_completed_assignments / total_assigned, 1)
            if total_assigned
            else None,
            "finalized_attempts": len(final_attempts),
            "average_objective_percent": round(
                100 * total_objective_score / total_objective_possible, 1
            )
            if total_objective_possible and scored_attempt_count >= 5
            else None,
            "score_suppressed": scored_attempt_count < 5,
        },
        "daily_completions": [{"date": date, "count": count} for date, count in daily.items()],
        "exams": exam_rows,
        "score_privacy_threshold": 5,
    }


@router.get("/courses/{course_id}/analytics")
def course_analytics(
    course_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("instructor", "administrator")),
):
    course = db.get(Course, course_id)
    if not course or not can_review_course(course, user):
        fail(404, "Course not found")
    result = _course_analytics(db, course)
    audit_action(
        db,
        user.id,
        "course.analytics_read",
        "course",
        course.id,
        {"exam_count": result["summary"]["exam_count"]},
    )
    db.commit()
    return result


@router.get("/courses/{course_id}/analytics.csv")
def export_course_analytics(
    course_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("instructor", "administrator")),
):
    course = db.get(Course, course_id)
    if not course or not can_review_course(course, user):
        fail(404, "Course not found")
    result = _course_analytics(db, course)
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        [
            "course_code",
            "course_name",
            "exam_title",
            "exam_status",
            "assigned_students",
            "started_attempts",
            "completed_attempts",
            "in_progress_attempts",
            "completed_students",
            "completion_percent",
            "average_objective_percent",
            "score_suppressed",
        ]
    )
    for exam in result["exams"]:
        row = [
            result["course"]["code"],
            result["course"]["name"],
            exam["title"],
            exam["status"],
            exam["assigned_students"],
            exam["started_attempts"],
            exam["completed_attempts"],
            exam["in_progress_attempts"],
            exam["completed_students"],
            exam["completion_percent"],
            exam["average_objective_percent"],
            exam["score_suppressed"],
        ]
        writer.writerow(
            [
                f"'{value}"
                if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r"))
                else value
                for value in row
            ]
        )
    audit_action(
        db,
        user.id,
        "course.analytics_exported",
        "course",
        course.id,
        {"exam_count": result["summary"]["exam_count"], "format": "csv"},
    )
    db.commit()
    safe_code = "".join(
        character for character in course.code if character.isalnum() or character in "-_"
    )
    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_code or "course"}-analytics.csv"'
        },
    )
