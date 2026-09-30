from collections.abc import Callable
from datetime import UTC, datetime
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from jev_agent.console import view_models
from jev_agent.models import Job, JobStatus
from jev_agent.simulation import (
    STORIES,
    STORIES_BY_NAME,
    NotResumable,
    SimulationBusy,
    SimulationRunner,
    jev_configured,
)
from jev_agent.store import JobStore

router = APIRouter()

STORY_TITLES = {story.name: story.title for story in STORIES}
RECENT_JOBS = 6

# One-line confirmations shown after a redirect (`?notice=...`).
NOTICES = {
    "started": "Simulated run started. Watch it move through the pipeline below.",
    "resumed": "Resumed from the last checkpoint. Completed steps are not redone.",
    "resolved": "Escalation resolved. The job stays waiting; nothing was restarted.",
}


def _store(request: Request) -> JobStore:
    store: JobStore = request.app.state.store
    return store


def _simulations(request: Request) -> SimulationRunner:
    runner: SimulationRunner = request.app.state.simulations
    return runner


def _now(request: Request) -> datetime:
    clock: Callable[[], datetime] = request.app.state.clock
    return clock()


def _render(
    request: Request, template: str, context: dict[str, object], status_code: int = 200
) -> HTMLResponse:
    """Render with the context every page shares (nav badge, JEV banner, the
    live simulation, a post-redirect notice)."""
    shared: dict[str, object] = {
        "pending_escalation_count": len(_store(request).list_pending_escalations()),
        "jev_configured": jev_configured(),
        "live_job_id": _simulations(request).live_job_id,
        "stories": STORIES,
        "notice": NOTICES.get(request.query_params.get("notice", "")),
    }
    return request.app.state.templates.TemplateResponse(  # type: ignore[no-any-return]
        request, template, shared | context, status_code=status_code
    )


def _job_or_404(request: Request, job_id: str) -> Job:
    job = _store(request).get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No job with id {job_id}")
    return job


def _list_item(request: Request, job: Job, now: datetime) -> view_models.JobListItem:
    interrupted = _simulations(request).is_interrupted(job)
    return view_models.job_list_item(job, now, interrupted, STORY_TITLES)


def _job_context(request: Request, job: Job) -> dict[str, object]:
    store = _store(request)
    runner = _simulations(request)
    events = store.list_history(job.id)
    interrupted = runner.is_interrupted(job)
    live = job.id == runner.live_job_id
    story = STORIES_BY_NAME.get(job.simulation) if job.simulation else None
    badge, label = view_models.status_badge(job.status), view_models.status_label(job.status)
    if interrupted:
        badge, label = "badge-interrupted", "Interrupted"
    return {
        "job": job,
        "story": story,
        "badge": badge,
        "label": label,
        # Poll only while something can still change it; an interrupted job
        # waits for Resume.
        "active": view_models.is_active(job.status) and not interrupted,
        "live": live,
        "interrupted": interrupted,
        "budget": view_models.budget_summary(job, _now(request)),
        "tracks": view_models.job_tracks(
            job, store.list_checkpoints(job.id), events, live=live, interrupted=interrupted
        ),
        "attempts": view_models.display_attempts(store.list_checkpoints(job.id), events),
        "escalations": [view_models.escalation_view(e) for e in store.list_escalations(job.id)],
        "actors": view_models.ACTORS,
    }


async def _form(request: Request) -> dict[str, str]:
    # Form bodies are parsed by hand: `Form(...)` would pull in python-multipart
    # for a couple of plain text fields.
    fields = parse_qs((await request.body()).decode("utf-8"))
    return {name: values[0].strip() for name, values in fields.items() if values}


# --- Pages ---------------------------------------------------------------------


@router.get("/", response_class=HTMLResponse)
def overview(request: Request) -> HTMLResponse:
    store = _store(request)
    now = _now(request)
    jobs = store.list_jobs()
    pending = store.list_pending_escalations()
    return _render(
        request,
        "overview.html",
        {
            "stats": view_models.dashboard_stats(jobs, len(pending)),
            "recent": [_list_item(request, job, now) for job in jobs[:RECENT_JOBS]],
            "actors": view_models.ACTORS,
        },
    )


@router.get("/how-it-works", response_class=HTMLResponse)
def how_it_works(request: Request) -> HTMLResponse:
    return _render(request, "how_it_works.html", {"actors": view_models.ACTORS})


@router.get("/tour", response_class=HTMLResponse)
def tour(request: Request) -> HTMLResponse:
    store = _store(request)

    def latest(story: str) -> Job | None:
        jobs = store.list_jobs(story=story)
        return jobs[0] if jobs else None

    return _render(
        request,
        "tour.html",
        {"steps": view_models.tour_steps(latest), "stories_by_name": STORIES_BY_NAME},
    )


@router.get("/jobs", response_class=HTMLResponse)
def job_list(request: Request) -> HTMLResponse:
    params = request.query_params
    status_value = params.get("status", "")
    status = JobStatus(status_value) if status_value in set(JobStatus) else None
    kind = params.get("kind", "")
    simulated = {"simulated": True, "real": False}.get(kind)
    story = params.get("story", "") or None
    query = params.get("q", "").strip()
    now = _now(request)
    jobs = _store(request).list_jobs(
        status=status, simulated=simulated, story=story, id_prefix=query or None
    )
    return _render(
        request,
        "jobs.html",
        {
            "rows": [_list_item(request, job, now) for job in jobs],
            "filters": {
                "status": status.value if status else "",
                "kind": kind if simulated is not None else "",
                "story": story or "",
                "q": query,
            },
            "filtered": any((status, simulated is not None, story, query)),
            "statuses": [(s.value, view_models.status_label(s)) for s in JobStatus],
        },
    )


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
            "pending": [view_models.escalation_view(e) for e in store.list_pending_escalations()],
            "resolved": [view_models.escalation_view(e) for e in store.list_resolved_escalations()],
        },
    )


# --- Actions (the console's only writes) ----------------------------------------


@router.post("/escalations/{escalation_id}/resolve")
async def resolve_escalation(request: Request, escalation_id: int) -> Response:
    note = (await _form(request)).get("note", "")
    try:
        escalation = _store(request).resolve_escalation(escalation_id, note)
    except KeyError:
        raise HTTPException(
            status_code=404, detail=f"No escalation with id {escalation_id}"
        ) from None
    return RedirectResponse(f"/jobs/{escalation.job_id}?notice=resolved", status_code=303)


@router.post("/simulations")
async def start_simulation(request: Request) -> Response:
    story = (await _form(request)).get("story", "")
    if story not in STORIES_BY_NAME:
        raise HTTPException(status_code=422, detail=f"There is no story called '{story}'.")
    try:
        job = _simulations(request).start(story)
    except SimulationBusy as busy:
        raise HTTPException(status_code=409, detail=str(busy)) from None
    return RedirectResponse(f"/jobs/{job.id}?notice=started", status_code=303)


@router.post("/jobs/{job_id}/resume")
def resume_simulation(request: Request, job_id: str) -> Response:
    _job_or_404(request, job_id)
    try:
        _simulations(request).resume(job_id)
    except (NotResumable, SimulationBusy) as refused:
        raise HTTPException(status_code=409, detail=str(refused)) from None
    return RedirectResponse(f"/jobs/{job_id}?notice=resumed", status_code=303)


def utc_now() -> datetime:
    return datetime.now(UTC)
