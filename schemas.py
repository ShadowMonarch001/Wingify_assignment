## ─────────────────────────────────────────────────────────────────────────────
## schemas.py  —  Pydantic v2 schemas for API request/response validation
## ─────────────────────────────────────────────────────────────────────────────
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


# ── User schemas ──────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    email: EmailStr
    name: Optional[str] = None


class UserResponse(BaseModel):
    id: str
    email: str
    name: Optional[str]
    api_key: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Job schemas ───────────────────────────────────────────────────────────────

class JobSubmitResponse(BaseModel):
    """Returned immediately when a job is accepted into the queue."""
    job_id: str
    status: str
    message: str
    poll_url: str


class JobStatusResponse(BaseModel):
    """
    Returned when polling job status.

    BUG FIX #9: The ORM model (AnalysisJob) has a primary key column named `id`,
    but this schema declared `job_id: str`. With `from_attributes=True` Pydantic
    reads attributes by name — it looks for `.job_id` on the ORM object, finds
    nothing, and either raises a ValidationError or silently returns None.

    Fix: declare `job_id` as an alias for the ORM's `id` field using
    `Field(alias="id")`, and enable `populate_by_name=True` so the field can
    also be set by its Python name (e.g. when constructing from a dict).
    """
    job_id: str = Field(alias="id")
    status: str
    query: str
    original_filename: Optional[str]
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    duration_seconds: Optional[float]
    error_message: Optional[str]
    retry_count: int

    model_config = {
        "from_attributes": True,
        "populate_by_name": True,  # allow both `id` (ORM alias) and `job_id` (Python name)
    }


# ── Result schemas ────────────────────────────────────────────────────────────

class AnalysisResultResponse(BaseModel):
    """Full analysis result — returned once the job is COMPLETED."""
    job_id: str
    status: str
    query: str
    original_filename: Optional[str]
    duration_seconds: Optional[float]

    verification_output: Optional[str]
    analysis_output: Optional[str]
    investment_output: Optional[str]
    risk_output: Optional[str]
    market_output: Optional[str]
    full_output: Optional[str]

    entity_name: Optional[str]
    document_type: Optional[str]
    reporting_period: Optional[str]

    created_at: datetime

    model_config = {"from_attributes": True}


class JobListResponse(BaseModel):
    jobs: list[JobStatusResponse]
    total: int
    limit: int
    offset: int


# ── Health check ──────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    version: str
    database: str
    redis: str