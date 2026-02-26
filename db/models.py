## ─────────────────────────────────────────────────────────────────────────────
## db/models.py  —  SQLAlchemy ORM models
## ─────────────────────────────────────────────────────────────────────────────
import uuid
import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Text, DateTime, Enum as SAEnum,
    ForeignKey, Integer, Float
)
from sqlalchemy.orm import relationship

# BUG FIX #6: Do NOT declare a new Base here.
# The original code had `Base = declarative_base()` which created a SECOND,
# separate Base object from the one in db/database.py.
# When create_tables() called database.Base.metadata.create_all(), it only
# knew about tables registered on *that* Base — which was zero, because all
# models were registered on *this* (different) Base.
# Result: create_tables() silently succeeded but created NO tables at all.
# Fix: import the single shared Base from db/database.py so all models are
# registered on the same metadata object that create_tables() uses.
from db.database import Base


class JobStatus(str, enum.Enum):
    PENDING    = "pending"
    PROCESSING = "processing"
    COMPLETED  = "completed"
    FAILED     = "failed"


class User(Base):
    """A user who submits analysis requests."""
    __tablename__ = "users"

    id         = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email      = Column(String(255), unique=True, nullable=False, index=True)
    name       = Column(String(255), nullable=True)
    api_key    = Column(String(64),  unique=True, nullable=False, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    jobs = relationship("AnalysisJob", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email}>"


class AnalysisJob(Base):
    """One document-analysis request submitted by a user."""
    __tablename__ = "analysis_jobs"

    id                = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id           = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    status            = Column(SAEnum(JobStatus), nullable=False, default=JobStatus.PENDING, index=True)
    query             = Column(Text, nullable=False)
    original_filename = Column(String(255), nullable=True)

    celery_task_id    = Column(String(255), nullable=True, index=True)

    created_at        = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    started_at        = Column(DateTime, nullable=True)
    completed_at      = Column(DateTime, nullable=True)
    duration_seconds  = Column(Float, nullable=True)

    error_message     = Column(Text, nullable=True)
    retry_count       = Column(Integer, default=0)

    user   = relationship("User", back_populates="jobs")
    result = relationship(
        "AnalysisResult", back_populates="job",
        uselist=False, cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<AnalysisJob id={self.id} status={self.status}>"


class AnalysisResult(Base):
    """The full output from a completed analysis job — one row per job."""
    __tablename__ = "analysis_results"

    id      = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id  = Column(String(36), ForeignKey("analysis_jobs.id"), nullable=False, unique=True)

    verification_output = Column(Text, nullable=True)
    analysis_output     = Column(Text, nullable=True)
    investment_output   = Column(Text, nullable=True)
    risk_output         = Column(Text, nullable=True)
    market_output       = Column(Text, nullable=True)

    full_output         = Column(Text, nullable=True)

    entity_name         = Column(String(255), nullable=True)
    document_type       = Column(String(255), nullable=True)
    reporting_period    = Column(String(255), nullable=True)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    job = relationship("AnalysisJob", back_populates="result")

    def __repr__(self) -> str:
        return f"<AnalysisResult id={self.id} job_id={self.job_id}>"