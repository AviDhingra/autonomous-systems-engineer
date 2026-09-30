"""Milestone 6 group 5: rendered pages carry their key content, degrade
without JavaScript, and draw the right stepper state for each story."""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jev_agent.console.app import create_app
from jev_agent.console.view_models import ACTORS
from jev_agent.demo_console_seed import seed_demo
from jev_agent.models import Job
from jev_agent.simulation import INSTANT, STORIES
from jev_agent.store import JobStore

PAGES = ["/", "/how-it-works", "/tour", "/jobs", "/escalations"]


@pytest.fixture(scope="module")
def seeded(tmp_path_factory: pytest.TempPathFactory) -> tuple[TestClient, dict[str, Job]]:
    tmp = tmp_path_factory.mktemp("design")
    url = f"sqlite:///{tmp / 'design.db'}"
    jobs = seed_demo(
        JobStore(url), stand_in_judges=True, instant=True, sandbox_root=tmp / "sandboxes"
    )
    app = create_app(url, pacing=INSTANT, sandbox_root=tmp / "sandboxes", background=False)
    return TestClient(app), jobs


def _states(html: str) -> list[list[str]]:
    """Pipeline step states per attempt track, as rendered."""
    tracks = html.split('class="track"')[1:]
    return [re.findall(r'class="pipe-step pipe-(\w+)', track) for track in tracks]


@pytest.mark.parametrize("path", PAGES)
def test_every_page_pins_its_scripts_and_marks_nav(
    seeded: tuple[TestClient, dict[str, Job]], path: str
) -> None:
    client, _ = seeded

    html = client.get(path).text

    assert "https://unpkg.com/htmx.org@2.0.4" in html
    assert "https://unpkg.com/alpinejs@3.14.1/dist/cdn.min.js" in html
    assert html.count('aria-current="page"') == 1
    assert 'href="/#run"' in html  # "Run a scenario" works as a plain link without JS


def test_run_dialog_offers_every_story_on_every_page(
    seeded: tuple[TestClient, dict[str, Job]],
) -> None:
    client, _ = seeded

    for path in PAGES:
        html = client.get(path).text
        for story in STORIES:
            assert f'name="story" value="{story.name}"' in html, (path, story.name)


def test_how_it_works_diagram_is_accessible_and_names_actors(
    seeded: tuple[TestClient, dict[str, Job]],
) -> None:
    client, _ = seeded

    html = client.get("/how-it-works").text

    assert 'role="img"' in html
    assert '<title id="loop-title">' in html
    assert '<desc id="loop-desc">' in html
    for actor in ACTORS.values():
        assert actor.label in html
    for label in ("Propose", "Apply", "Verify", "JEV judgment", "Policy decides", "Budgets"):
        assert f">{label}</text>" in html


def test_tour_lists_every_step_without_javascript(
    seeded: tuple[TestClient, dict[str, Job]],
) -> None:
    client, _ = seeded

    html = client.get("/tour").text

    assert html.count('class="tour-step"') == 6
    # Step controls exist only for Alpine; without it they stay hidden.
    assert (
        'class="tour-progress" aria-label="Tour steps" x-show="true" style="display: none"' in html
    )


def test_notice_renders_as_dismissible_toast(seeded: tuple[TestClient, dict[str, Job]]) -> None:
    client, _ = seeded

    html = client.get("/?notice=resolved").text

    assert 'class="toast"' in html
    assert "Escalation resolved" in html
    assert 'aria-label="Dismiss"' in html
    assert 'class="toast"' not in client.get("/?notice=bogus").text


def test_badges_pair_status_color_with_a_label(seeded: tuple[TestClient, dict[str, Job]]) -> None:
    client, _ = seeded

    html = client.get("/jobs").text

    for label in ("Succeeded", "Failed", "Waiting on escalation"):
        assert f'<span class="dot" aria-hidden="true"></span>{label}</span>' in html


def test_overview_status_bar_has_text_alternative(
    seeded: tuple[TestClient, dict[str, Job]],
) -> None:
    client, _ = seeded

    html = client.get("/").text

    assert 'class="breakdown-bar" role="img" aria-label="Jobs by status:' in html
    assert "Succeeded 3" in html


@pytest.mark.parametrize(
    ("story", "expected"),
    [
        ("happy-path", [["done", "done", "done"]]),
        ("crash-resume", [["done", "done", "done"]]),
        ("retry-then-pass", [["done", "done", "failed"], ["done", "done", "done"]]),
        ("jev-stop", [["done", "done", "failed"]]),
        ("retry-budget", [["done", "done", "failed"], ["done", "done", "failed"]]),
        ("step-failure", [["failed", "pending", "pending"]]),
    ],
)
def test_stepper_states_per_story(
    seeded: tuple[TestClient, dict[str, Job]], story: str, expected: list[list[str]]
) -> None:
    client, jobs = seeded

    html = client.get(f"/jobs/{jobs[story].id}/status").text

    assert _states(html) == expected


def test_decision_nodes_follow_failed_attempts(seeded: tuple[TestClient, dict[str, Job]]) -> None:
    client, jobs = seeded

    budget = client.get(f"/jobs/{jobs['retry-budget'].id}/status").text
    happy = client.get(f"/jobs/{jobs['happy-path'].id}/status").text

    assert budget.count('class="decision decision-') == 2
    assert "Policy: Retry" in budget
    assert "Policy: Escalate (Retry budget exhausted)" in budget
    assert 'class="decision decision-' not in happy


def test_job_page_has_legend_and_collapsed_history(
    seeded: tuple[TestClient, dict[str, Job]],
) -> None:
    client, jobs = seeded

    html = client.get(f"/jobs/{jobs['retry-then-pass'].id}").text

    assert '<details class="history-box">' in html
    for actor in ACTORS.values():
        assert f'class="actor-chip actor-{actor.key}">{actor.label}' in html


def test_stylesheet_defines_both_themes_and_actor_colors() -> None:
    css = (
        Path(__file__).parents[2] / "src" / "jev_agent" / "console" / "static" / "console.css"
    ).read_text(encoding="utf-8")

    assert "@media (prefers-color-scheme: dark)" in css
    assert ':root[data-theme="dark"]' in css
    for key in ACTORS:
        assert f"--actor-{key}:" in css
    assert "prefers-reduced-motion" in css


def test_busy_console_keeps_story_buttons_disabled_under_alpine(tmp_path: Path) -> None:
    import threading

    from jev_agent.models import Judgment, Retryability

    release = threading.Event()

    def blocking(state: dict[str, object]) -> Judgment:
        release.wait(timeout=10)
        return Judgment(retryability=Retryability.RETRYABLE, confidence=0.9)

    app = create_app(
        f"sqlite:///{tmp_path / 'busy.db'}",
        pacing=INSTANT,
        judge_fn=blocking,
        sandbox_root=tmp_path / "sandboxes",
    )
    client = TestClient(app, follow_redirects=False)
    try:
        client.post(
            "/simulations",
            content="story=retry-then-pass",
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        html = client.get("/").text
        # The Alpine binding must not re-enable a button the server disabled.
        assert ':disabled="busy || true" disabled' in html
        assert ':disabled="busy || false"' not in html
    finally:
        release.set()
        app.state.simulations.wait(timeout=10)
