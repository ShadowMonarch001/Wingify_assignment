## ─────────────────────────────────────────────────────────────────────────────
## worker/celery_app.py  —  Celery application + analysis task
## ─────────────────────────────────────────────────────────────────────────────
import os
import logging

from celery import Celery
from celery.utils.log import get_task_logger
from dotenv import load_dotenv

load_dotenv()

logger = get_task_logger(__name__)

REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

app = Celery(
    "financial_analyzer",
    broker=REDIS_URL,
    backend=REDIS_URL,
)

app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=900,        # 15 min — headroom for rate-limit retries
    task_time_limit=960,             # 16 min hard kill
    task_max_retries=5,              # up from 3 — rate limit retries need more room
    result_expires=86400,
    task_default_queue="analysis",
)


# ── Celery task ───────────────────────────────────────────────────────────────

@app.task(
    bind=True,
    name="worker.celery_app.run_analysis",
    max_retries=5,
    default_retry_delay=60,
)
def run_analysis(self, job_id: str, query: str, file_path: str) -> dict:
    """
    Celery task: run the full 5-agent CrewAI pipeline for one analysis job.
    """
    from crewai import Crew, Process
    from agents import (
        verifier, financial_analyst,
        investment_advisor, risk_assessor, market_analyst,
    )
    from task import (
        verification, analyze_financial_document,
        investment_analysis, risk_assessment, market_insights,
    )
    from db.database import get_db_context
    from db.crud import (
        mark_job_processing, mark_job_completed,
        mark_job_failed, create_result,
    )

    # ── 1. Mark job as PROCESSING ─────────────────────────────────────────────
    with get_db_context() as db:
        mark_job_processing(db, job_id=job_id, celery_task_id=self.request.id)

    # ── 2. Run the CrewAI pipeline ────────────────────────────────────────────
    full_output = None
    try:
        logger.info(f"[Job {job_id}] Starting CrewAI pipeline | query='{query[:80]}'")

        crew = Crew(
            agents=[verifier, financial_analyst, investment_advisor, risk_assessor, market_analyst],
            tasks=[
                verification,
                analyze_financial_document,
                investment_analysis,
                risk_assessment,
                market_insights,
            ],
            process=Process.sequential,
            verbose=False,
        )

        crew_result = crew.kickoff(inputs={"query": query, "file_path": file_path})
        full_output = str(crew_result)
        logger.info(f"[Job {job_id}] CrewAI pipeline completed successfully")

    except Exception as exc:
        error_str = str(exc)
        is_rate_limit = "429" in error_str or "RateLimitError" in error_str or "rate-limited" in error_str.lower()

        if is_rate_limit and self.request.retries < self.max_retries:
            # Rate limit: back off longer — 60s, 120s, 240s
            countdown = 60 * (2 ** self.request.retries)
            logger.warning(
                f"[Job {job_id}] Rate limited by LLM provider (attempt {self.request.retries + 1}/{self.max_retries}). "
                f"Retrying in {countdown}s..."
            )
            # Don't mark as failed yet — it's just waiting
            raise self.retry(exc=exc, countdown=countdown)

        logger.error(f"[Job {job_id}] CrewAI pipeline failed: {exc}", exc_info=True)

        with get_db_context() as db:
            mark_job_failed(db, job_id=job_id, error_message=error_str)

        _cleanup_file(job_id, file_path)

        raise self.retry(exc=exc, countdown=30 * (2 ** self.request.retries))

    # ── 3. Persist result and mark COMPLETED ─────────────────────────────────
    # BUG FIX #8: File cleanup now happens AFTER the DB write succeeds,
    # not in a finally block that ran before this code in the original.
    try:
        with get_db_context() as db:
            create_result(
                db,
                job_id=job_id,
                full_output=full_output,
            )
            mark_job_completed(db, job_id=job_id)
        logger.info(f"[Job {job_id}] Result persisted. Job marked COMPLETED.")
    finally:
        # Safe to delete now — DB write is done (or failed unrecoverably)
        _cleanup_file(job_id, file_path)

    return {
        "job_id": job_id,
        "status": "completed",
        "full_output": full_output,
    }


def _cleanup_file(job_id: str, file_path: str) -> None:
    """Remove the temporary PDF upload file, logging any errors."""
    if file_path and os.path.exists(file_path):
        try:
            os.remove(file_path)
            logger.debug(f"[Job {job_id}] Cleaned up temp file: {file_path}")
        except OSError as e:
            logger.warning(f"[Job {job_id}] Could not remove temp file {file_path}: {e}")