## ─────────────────────────────────────────────────────────────────────────────
## main.py  —  FastAPI application
## ─────────────────────────────────────────────────────────────────────────────
import asyncio
import os
import uuid
import logging
from contextlib import asynccontextmanager
from typing import Optional

import redis
from fastapi import (
    FastAPI, File, UploadFile, Form, HTTPException,
    Depends, Header, Query
)
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from db.database import create_tables, get_db
from db.crud import (
    create_job, get_job, get_jobs_for_user, get_recent_jobs,
    get_result_for_job, create_user, get_user_by_api_key, get_user_by_email,
)
from db.models import JobStatus
from schemas import (
    AnalysisResultResponse, HealthResponse,
    JobListResponse, JobStatusResponse, JobSubmitResponse,
    UserCreate, UserResponse,
)
from worker.celery_app import run_analysis

logger = logging.getLogger(__name__)

REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")


# ── Startup / shutdown ────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    BUG FIX #3: Two problems existed in the original lifespan:

    Problem A — time.sleep() in an async function.
      time.sleep() is a *blocking* call. Inside an async function it freezes the
      entire event loop for 10 seconds, preventing uvicorn from handling any
      requests or running other coroutines. The correct call is asyncio.sleep().

    Problem B — No retry loop.
      PostgreSQL (especially in Docker) may not be ready the instant the API
      container starts, even with healthcheck depends_on. A single attempt that
      fails leaves the app running with no tables and every DB call fails with
      "relation does not exist". The fix is a retry loop with back-off so the
      app keeps trying until Postgres is genuinely ready.

    Combined effect of original bugs: with --workers 2 and a blocking sleep,
    table creation would often not complete at all, giving the persistent
    UndefinedTable errors you saw.
    """
    logger.info("Lifespan: waiting for database to be ready...")
    last_error = None

    for attempt in range(1, 11):                      # up to 10 attempts
        try:
            create_tables()                           # idempotent — safe to call repeatedly
            logger.info(f"Tables created/verified successfully (attempt {attempt})")
            last_error = None
            break
        except Exception as e:
            last_error = e
            logger.warning(
                f"DB not ready yet (attempt {attempt}/10): {e} — retrying in 3s..."
            )
            await asyncio.sleep(3)                    # FIX A: non-blocking sleep

    if last_error:
        # Log the failure but don't crash — the app can still serve health checks
        # and the operator can investigate. Every endpoint that hits the DB will
        # fail with a clear error rather than a silent startup crash.
        logger.error(
            "Could not create tables after 10 attempts. "
            "Verify PostgreSQL is reachable and credentials are correct. "
            f"Last error: {last_error}"
        )

    yield
    logger.info("Lifespan ended")


# ── App factory ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="Financial Document Analyzer",
    description=(
        "AI-powered multi-agent financial document analysis system.\n\n"
        "**Pipeline:** Document Verification → Financial Analysis → "
        "Investment Insights → Risk Assessment → Market Intelligence\n\n"
        "**Queue model:** Requests are submitted asynchronously via Celery + Redis. "
        "Poll `/jobs/{job_id}` for status and `/jobs/{job_id}/result` for the full output."
    ),
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Auth dependency ───────────────────────────────────────────────────────────
def get_current_user_optional(
    x_api_key: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    """
    Return the User if a valid API key is provided, else None (anonymous allowed).

    BUG FIX #4: Original code returned None for an *invalid* key — a key that
    was provided but didn't match any user. This silently ran the job as
    anonymous instead of rejecting the bad credential.
    Fix: only allow None when NO key was provided at all. A provided-but-wrong
    key gets a 401.
    """
    if not x_api_key:
        return None
    user = get_user_by_api_key(db, x_api_key)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid API key.")
    return user


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/", response_model=HealthResponse, tags=["Health"])
async def root():
    """Health check — verifies API, database, and Redis connectivity."""
    db_status = "ok"
    redis_status = "ok"

    try:
        from db.database import engine
        with engine.connect() as conn:
            conn.execute(__import__("sqlalchemy").text("SELECT 1"))
    except Exception as e:
        db_status = f"error: {e}"

    try:
        r = redis.Redis.from_url(REDIS_URL, socket_connect_timeout=2)
        r.ping()
    except Exception as e:
        redis_status = f"error: {e}"

    return HealthResponse(
        status="ok" if db_status == "ok" and redis_status == "ok" else "degraded",
        version="2.0.0",
        database=db_status,
        redis=redis_status,
    )


# ── User management ───────────────────────────────────────────────────────────
@app.post("/users", response_model=UserResponse, tags=["Users"], status_code=201)
async def register_user(payload: UserCreate, db: Session = Depends(get_db)):
    """
    Register a new user and receive an API key.

    The API key must be passed as the `X-Api-Key` header on subsequent requests
    to associate jobs with your account and access your job history.
    """
    existing = get_user_by_email(db, payload.email)
    if existing:
        raise HTTPException(status_code=409, detail="A user with this email already exists.")
    user = create_user(db, email=payload.email, name=payload.name)
    return user


@app.get("/users/me", response_model=UserResponse, tags=["Users"])
async def get_me(
    x_api_key: str = Header(...),
    db: Session = Depends(get_db),
):
    """Return the authenticated user's profile."""
    user = get_user_by_api_key(db, x_api_key)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid API key.")
    return user


# ── Submit analysis job ───────────────────────────────────────────────────────
@app.post("/analyze", response_model=JobSubmitResponse, tags=["Analysis"], status_code=202)
async def submit_analysis(
    file: UploadFile = File(...),
    query: str = Form(default="Analyze this financial document for investment insights"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_optional),
):
    """
    **Submit a financial PDF for analysis.**

    The request is accepted immediately (HTTP 202) and processed asynchronously
    by a Celery worker. Use the returned `job_id` to poll for status and results.

    - **file**: PDF financial document
    - **query**: Specific analysis question (optional)
    - **X-Api-Key** header: Optional — associates the job with your account

    Returns a `job_id` and a `poll_url` to check progress.
    """
    # Validate: not empty
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    # BUG FIX #5: Check both the filename extension AND the declared content-type.
    # Original only checked the extension, so a renamed .txt file would pass.
    if (
        not file.filename.lower().endswith(".pdf")
        or file.content_type not in ("application/pdf", "application/octet-stream")
    ):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    # Normalise query
    query = (
        query.strip()
        if query and query.strip()
        else "Analyze this financial document for investment insights"
    )

    os.makedirs("data", exist_ok=True)
    file_path: str | None = None

    try:
        file_path = os.path.abspath(f"data/upload_{str(uuid.uuid4())}.pdf")
        with open(file_path, "wb") as f:
            f.write(content)

        # Create DB record
        job = create_job(
            db,
            query=query,
            original_filename=file.filename,
            user_id=current_user.id if current_user else None,
        )

        # Enqueue Celery task
        task = run_analysis.apply_async(
            kwargs={"job_id": job.id, "query": query, "file_path": file_path},
            queue="analysis",
        )

        # Store Celery task ID on the job row
        job.celery_task_id = task.id
        db.commit()

    except HTTPException:
        raise

    except Exception as e:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError:
                pass
        raise HTTPException(
            status_code=500,
            detail=f"Failed to enqueue analysis job: {str(e)}",
        )

    return JobSubmitResponse(
        job_id=job.id,
        status=JobStatus.PENDING,
        message="Job accepted and queued for processing. Poll the status URL for updates.",
        poll_url=f"/jobs/{job.id}",
    )


# ── Job status polling ────────────────────────────────────────────────────────
@app.get("/jobs/{job_id}", response_model=JobStatusResponse, tags=["Jobs"])
async def get_job_status(job_id: str, db: Session = Depends(get_db)):
    """
    **Poll job status.**

    Returns current status: `pending` → `processing` → `completed` | `failed`.
    """
    job = get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    return job


@app.get("/jobs/{job_id}/result", response_model=AnalysisResultResponse, tags=["Jobs"])
async def get_job_result(job_id: str, db: Session = Depends(get_db)):
    """
    **Retrieve the full analysis result for a completed job.**
    """
    job = get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    if job.status == JobStatus.PENDING:
        raise HTTPException(status_code=202, detail="Job is still pending in the queue.")
    if job.status == JobStatus.PROCESSING:
        raise HTTPException(status_code=202, detail="Job is currently being processed.")
    if job.status == JobStatus.FAILED:
        raise HTTPException(
            status_code=500,
            detail=f"Job failed: {job.error_message or 'Unknown error'}",
        )

    result = get_result_for_job(db, job_id)
    if not result:
        raise HTTPException(status_code=404, detail="Result not found for this job.")

    return AnalysisResultResponse(
        job_id=job.id,
        status=job.status,
        query=job.query,
        original_filename=job.original_filename,
        duration_seconds=job.duration_seconds,
        verification_output=result.verification_output,
        analysis_output=result.analysis_output,
        investment_output=result.investment_output,
        risk_output=result.risk_output,
        market_output=result.market_output,
        full_output=result.full_output,
        entity_name=result.entity_name,
        document_type=result.document_type,
        reporting_period=result.reporting_period,
        created_at=result.created_at,
    )


@app.get("/jobs", response_model=JobListResponse, tags=["Jobs"])
async def list_jobs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    x_api_key: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    """
    **List analysis jobs.**

    - With a valid `X-Api-Key` header: returns your own jobs.
    - Without a key: returns the 20 most recent jobs (all users).
    """
    if x_api_key:
        user = get_user_by_api_key(db, x_api_key)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid API key.")
        jobs = get_jobs_for_user(db, user_id=user.id, limit=limit, offset=offset)
        total = len(jobs)
    else:
        jobs = get_recent_jobs(db, limit=limit)
        total = len(jobs)

    return JobListResponse(jobs=jobs, total=total, limit=limit, offset=offset)


@app.delete("/jobs/{job_id}", status_code=204, tags=["Jobs"])
async def delete_job(
    job_id: str,
    x_api_key: str = Header(...),
    db: Session = Depends(get_db),
):
    """**Delete a job and its result.** Requires the API key of the job owner."""
    user = get_user_by_api_key(db, x_api_key)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid API key.")

    job = get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    if job.user_id != user.id:
        raise HTTPException(status_code=403, detail="You do not own this job.")
    if job.status == JobStatus.PROCESSING:
        raise HTTPException(status_code=409, detail="Cannot delete a job that is currently processing.")

    db.delete(job)
    db.commit()
    return None


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)