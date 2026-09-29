from collections.abc import Callable
from datetime import UTC, datetime
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from jev_agent.console import view_models
from jev_agent.history_format import format_event
from jev_agent.models import Job
from jev_agent.store import JobStore

router = APIRouter()


def _store(request: Request) -> JobStore:
    store: JobStore = request.app.state.store
    return store


def _now(request: Request) -> datetime:
    clock: Callable[[], datetime] = request.app.state.clock
    return clock()


def _render(request: Request, template: str, context: dict[str, object]) -> HTMLResponse:
    return request.app.state.templates.TemplateResponse(request, template, context)  # type: ignore[no-any-return]


def _job_or_404(request: Request, job_id: str) -> Job:
    job = _store(request).get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No job with id {job_id}")
    return job


def _job_context(request: Request, job: Job) -> dict[str, object]:
    store = _store(request)
    events = store.list_history(job.id)
    return {
        "job": job,
        "badge": view_models.status_badge(job.status),
        "label": view_models.status_label(job.status),
        "active": view_models.is_active(job.status),
        "budget": view_models.budget_summary(job, _now(request)),
        "attempts": view_models.group_by_attempt(store.list_checkpoints(job.id), events),
        "escalations": store.list_escalations(job.id),
        "events": events,
        "format_event": format_event,
        "judgment_summary": view_models.judgment_summary,
    }


@router.get("/", response_class=HTMLResponse)
def job_list(request: Request) -> HTMLResponse:
    now = _now(request)
    rows = [
        {
            "job": job,
            "badge": view_models.status_badge(job.status),
            "label": view_models.status_label(job.status),
            "elapsed": view_models.humanize_duration(view_models.elapsed_seconds(job, now)),
        }
        for job in _store(request).list_jobs()
    ]
    return _render(request, "jobs.html", {"rows": rows})


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_detail(request: Request, job_id: str) -> HTMLResponse:
    job = _job_or_404(request, job_id)
    return _render(request, "job.html", _job_context(request, job))


@router.get("/jobs/{job_id}/status", response_class=HTMLResponse)
def job_status_fragment(request: Request, job_id: str) -> HTMLResponse:
    job = _job_or_404(request, job_id)
    return _render(request, "fragments/status.html", _job_context(request, job))


@router.get("/jobs/{job_id}/history", response_class=HTMLResponse)
def job_history_fragment(request: Request, job_id: str) -> HTMLResponse:
    job = _job_or_404(request, job_id)
    return _render(request, "fragments/history.html", _job_context(request, job))


@router.get("/escalations", response_class=HTMLResponse)
def escalation_list(request: Request) -> HTMLResponse:
    store = _store(request)
    return _render(
        request,
        "escalations.html",
        {
            "pending": store.list_pending_escalations(),
            "resolved": store.list_resolved_escalations(),
        },
    )


@router.post("/escalations/{escalation_id}/resolve")
async def resolve_escalation(request: Request, escalation_id: int) -> Response:
    # Form bodies are parsed by hand: `Form(...)` would pull in python-multipart
    # for what is one optional text field.
    fields = parse_qs((await request.body()).decode("utf-8"))
    note = fields.get("note", [""])[0].strip()
    store = _store(request)
    try:
        escalation = store.resolve_escalation(escalation_id, note)
    except KeyError:
        raise HTTPException(
            status_code=404, detail=f"No escalation with id {escalation_id}"
        ) from None
    return RedirectResponse(f"/jobs/{escalation.job_id}", status_code=303)


def utc_now() -> datetime:
    return datetime.now(UTC)
