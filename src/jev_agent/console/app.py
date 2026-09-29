from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from jev_agent.console.routes import router, utc_now
from jev_agent.store import DEFAULT_DATABASE_URL, JobStore

CONSOLE_DIR = Path(__file__).parent


def create_app(
    database_url: str = DEFAULT_DATABASE_URL,
    clock: Callable[[], datetime] = utc_now,
) -> FastAPI:
    """Build the console app around one `JobStore`.

    `clock` supplies "now" for elapsed-time displays (tests inject a fixed one)."""
    app = FastAPI(title="JEV Execution Console")
    app.state.store = JobStore(database_url)
    app.state.clock = clock
    app.state.templates = Jinja2Templates(directory=CONSOLE_DIR / "templates")
    app.mount("/static", StaticFiles(directory=CONSOLE_DIR / "static"), name="static")
    app.include_router(router)

    @app.exception_handler(404)
    def not_found(request: Request, exc: Exception) -> HTMLResponse:
        detail = exc.detail if isinstance(exc, HTTPException) else "Page not found"
        response: HTMLResponse = app.state.templates.TemplateResponse(
            request, "not_found.html", {"detail": detail}, status_code=404
        )
        return response

    return app
