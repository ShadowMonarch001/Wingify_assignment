## ─────────────────────────────────────────────────────────────────────────────
## db/crud.py  —  Database CRUD operations (no business logic here)
## ─────────────────────────────────────────────────────────────────────────────
import secrets
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from db.models import AnalysisJob, AnalysisResult, JobStatus, User


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_aware(dt: Optional[datetime]) -> Optional[datetime]:
    """
    BUG FIX: Ensure a datetime is timezone-aware (UTC).

    PostgreSQL stores TIMESTAMP WITHOUT TIME ZONE columns. When SQLAlchemy reads
    them back, it returns naive datetime objects (no tzinfo). But `completed_at`
    is set with `datetime.now(timezone.utc)` which IS timezone-aware.

    Subtracting a naive datetime from an aware one raises:
        TypeError: can't subtract offset-naive and offset-aware datetimes

    This helper normalises any naive datetime to UTC-aware before arithmetic,
    which is safe because all datetimes in this app are stored in UTC.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ── User operations ───────────────────────────────────────────────────────────

def create_user(db: Session, email: str, name: Optional[str] = None) -> User:
    """Create a new user with a randomly generated API key."""
    user = User(
        id=str(uuid.uuid4()),
        email=email,
        name=name,
        api_key=secrets.token_urlsafe(32),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_user_by_api_key(db: Session, api_key: str) -> Optional[User]:
    return db.query(User).filter(User.api_key == api_key).first()


def get_user_by_email(db: Session, email: str) -> Optional[User]:
    return db.query(User).filter(User.email == email).first()


# ── Job operations ────────────────────────────────────────────────────────────

def create_job(
    db: Session,
    query: str,
    original_filename: Optional[str] = None,
    user_id: Optional[str] = None,
) -> AnalysisJob:
    """Create a new analysis job in PENDING state."""
    job = AnalysisJob(
        id=str(uuid.uuid4()),
        query=query,
        original_filename=original_filename,
        user_id=user_id,
        status=JobStatus.PENDING,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def get_job(db: Session, job_id: str) -> Optional[AnalysisJob]:
    return db.query(AnalysisJob).filter(AnalysisJob.id == job_id).first()


def get_jobs_for_user(
    db: Session,
    user_id: str,
    limit: int = 20,
    offset: int = 0,
) -> list[AnalysisJob]:
    return (
        db.query(AnalysisJob)
        .filter(AnalysisJob.user_id == user_id)
        .order_by(AnalysisJob.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def get_recent_jobs(db: Session, limit: int = 50) -> list[AnalysisJob]:
    return (
        db.query(AnalysisJob)
        .order_by(AnalysisJob.created_at.desc())
        .limit(limit)
        .all()
    )


def mark_job_processing(db: Session, job_id: str, celery_task_id: str) -> Optional[AnalysisJob]:
    job = get_job(db, job_id)
    if job:
        job.status = JobStatus.PROCESSING
        job.celery_task_id = celery_task_id
        job.started_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(job)
    return job


def mark_job_completed(db: Session, job_id: str) -> Optional[AnalysisJob]:
    job = get_job(db, job_id)
    if job:
        job.status = JobStatus.COMPLETED
        job.completed_at = datetime.now(timezone.utc)
        # BUG FIX: normalise started_at to UTC-aware before subtracting.
        # PostgreSQL TIMESTAMP WITHOUT TIME ZONE columns return naive datetimes;
        # completed_at is set with timezone.utc so it's aware. Python raises
        # TypeError if you subtract naive from aware. _make_aware() fixes this.
        started = _make_aware(job.started_at)
        if started:
            delta = job.completed_at - started
            job.duration_seconds = delta.total_seconds()
        db.commit()
        db.refresh(job)
    return job


def mark_job_failed(db: Session, job_id: str, error_message: str) -> Optional[AnalysisJob]:
    job = get_job(db, job_id)
    if job:
        job.status = JobStatus.FAILED
        job.completed_at = datetime.now(timezone.utc)
        job.error_message = error_message
        job.retry_count += 1
        # BUG FIX: same timezone normalisation as mark_job_completed.
        # This is the line that actually crashed in your logs:
        #   delta = job.completed_at - job.started_at
        #   TypeError: can't subtract offset-naive and offset-aware datetimes
        started = _make_aware(job.started_at)
        if started:
            delta = job.completed_at - started
            job.duration_seconds = delta.total_seconds()
        db.commit()
        db.refresh(job)
    return job


# ── Result operations ─────────────────────────────────────────────────────────

def create_result(
    db: Session,
    job_id: str,
    full_output: str,
    verification_output: Optional[str] = None,
    analysis_output: Optional[str] = None,
    investment_output: Optional[str] = None,
    risk_output: Optional[str] = None,
    market_output: Optional[str] = None,
    entity_name: Optional[str] = None,
    document_type: Optional[str] = None,
    reporting_period: Optional[str] = None,
) -> AnalysisResult:
    """Persist the full analysis result for a completed job."""
    result = AnalysisResult(
        id=str(uuid.uuid4()),
        job_id=job_id,
        full_output=full_output,
        verification_output=verification_output,
        analysis_output=analysis_output,
        investment_output=investment_output,
        risk_output=risk_output,
        market_output=market_output,
        entity_name=entity_name,
        document_type=document_type,
        reporting_period=reporting_period,
    )
    db.add(result)
    db.commit()
    db.refresh(result)
    return result


def get_result_for_job(db: Session, job_id: str) -> Optional[AnalysisResult]:
    return db.query(AnalysisResult).filter(AnalysisResult.job_id == job_id).first()