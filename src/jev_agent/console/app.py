from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from jev_agent.store import DEFAULT_DATABASE_URL, JobStore

CONSOLE_DIR = Path(__file__).parent


def create_app(database_url: str = DEFAULT_DATABASE_URL) -> FastAPI:
    """Build the console app around one `JobStore`.

    Routes are added by the routes task group; this wires the store, templates
    and static files so they are reachable as `app.state.*`."""
    app = FastAPI(title="JEV Execution Console")
    app.state.store = JobStore(database_url)
    app.state.templates = Jinja2Templates(directory=CONSOLE_DIR / "templates")
    app.mount("/static", StaticFiles(directory=CONSOLE_DIR / "static"), name="static")
    return app
