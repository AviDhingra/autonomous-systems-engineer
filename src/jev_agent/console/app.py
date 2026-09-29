from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from jev_agent.console.routes import router, utc_now
from jev_agent.runner import JudgeFn
from jev_agent.simulation import DEFAULT_PACING, SANDBOX_ROOT, Pacing, SimulationRunner
from jev_agent.store import DEFAULT_DATABASE_URL, JobStore

CONSOLE_DIR = Path(__file__).parent

ERROR_TITLES = {404: "Not found", 409: "Can't do that right now", 422: "Unknown request"}


def create_app(
    database_url: str = DEFAULT_DATABASE_URL,
    clock: Callable[[], datetime] = utc_now,
    *,
    pacing: Pacing = DEFAULT_PACING,
    judge_fn: JudgeFn | None = None,
    sandbox_root: Path = SANDBOX_ROOT,
    background: bool = True,
) -> FastAPI:
    """Build the console app around one `JobStore` and one `SimulationRunner`.

    `clock` supplies "now" for elapsed-time displays. `pacing`, `judge_fn`,
    `sandbox_root` and `background` configure simulated runs; the defaults
    are the real ones (paced steps, the live JEV judgment, a background
    thread). Tests inject instant, offline, synchronous versions."""
    app = FastAPI(title="JEV Execution Console")
    store = JobStore(database_url)
    app.state.store = store
    app.state.clock = clock
    app.state.simulations = SimulationRunner(
        store,
        pacing=pacing,
        judge_fn=judge_fn,
        sandbox_root=sandbox_root,
        background=background,
    )
    app.state.templates = Jinja2Templates(directory=CONSOLE_DIR / "templates")
    app.mount("/static", StaticFiles(directory=CONSOLE_DIR / "static"), name="static")
    app.include_router(router)

    def error_page(request: Request, exc: Exception) -> HTMLResponse:
        status = exc.status_code if isinstance(exc, HTTPException) else 404
        detail = exc.detail if isinstance(exc, HTTPException) else "Page not found"
        response: HTMLResponse = app.state.templates.TemplateResponse(
            request,
            "error.html",
            {"title": ERROR_TITLES.get(status, "Something went wrong"), "detail": detail},
            status_code=status,
        )
        return response

    for status in ERROR_TITLES:
        app.add_exception_handler(status, error_page)

    return app
