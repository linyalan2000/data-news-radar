"""Digest trigger endpoint — async 202 with job status polling."""
import uuid
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.auth import require_api_key
from app.api.deps import get_db, get_news_store
from app.config import settings
from app.notifier.digest_notifier import DigestNotifier
from app.schemas import DigestJobResponse, DigestJobStatus, DigestTriggerResult

router = APIRouter(dependencies=[Depends(require_api_key)])

# In-memory job registry — sufficient for single-process deployment
_jobs: dict[str, dict] = {}


def _run_digest_background(job_id: str, db: Session) -> None:
    """Background task: run the full digest pipeline and record result."""
    _jobs[job_id]["status"] = "running"
    try:
        store = get_news_store(db)
        notifier = DigestNotifier(
            news_store=store,
            smtp_config=settings.smtp_config,
            webhook_url=settings.digest_webhook_url,
            gemini_api_key=settings.gemini_api_key,
            gemini_model=settings.gemini_model,
            groq_api_key=settings.groq_api_key,
            groq_model=settings.groq_model,
            minimax_api_key=settings.minimax_api_key,
            minimax_model=settings.minimax_model,
            lookback_hours=settings.digest_lookback_hours,
            briefings_output_dir=settings.briefings_output_dir_resolved,
            user_context=settings.user_context,
            highlight_scorer_enabled=settings.FEATURES.get("highlight_scorer", False),
        )
        summary = notifier.run()
        _jobs[job_id]["status"] = "done"
        _jobs[job_id]["result"] = summary
    except Exception as exc:
        _jobs[job_id]["status"] = "failed"
        _jobs[job_id]["error"] = str(exc)
    finally:
        db.close()


@router.post("/api/digest/trigger", response_model=DigestJobResponse, status_code=202)
def trigger_digest(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"status": "queued", "result": None}
    background_tasks.add_task(_run_digest_background, job_id, db)
    return DigestJobResponse(job_id=job_id, status="queued")


@router.get("/api/digest/jobs/{job_id}", response_model=DigestJobStatus)
def get_digest_job_status(job_id: str):
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    result: Optional[DigestTriggerResult] = None
    if job.get("result"):
        result = DigestTriggerResult(**job["result"])
    return DigestJobStatus(job_id=job_id, status=job["status"], result=result)
