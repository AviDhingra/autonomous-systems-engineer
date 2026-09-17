from pathlib import Path

from ase.benchmark.runner import run_scenario
from ase.benchmark.scenario import Scenario
from ase.providers.errors import (
    ModelRateLimitError,
    ToolBudgetExceeded,
)
from ase.tools.repository import RepositoryTools


class ProviderFailingAgent:
    def investigate(
        self,
        ticket: str,
        tools: RepositoryTools,
    ):
        del ticket, tools
        raise ModelRateLimitError(
            "test provider limit"
        )


class BudgetFailingAgent:
    def investigate(
        self,
        ticket: str,
        tools: RepositoryTools,
    ):
        del ticket, tools
        raise ToolBudgetExceeded(
            "test tool budget"
        )


def _load_s01() -> tuple[Path, Scenario]:
    project_root = Path.cwd()
    scenario = Scenario.load(
        project_root
        / "scenarios"
        / "S01-duplicate-telemetry"
    )
    return project_root, scenario


def test_provider_failure_is_invalid_episode(
    tmp_path: Path,
) -> None:
    project_root, scenario = _load_s01()

    report = run_scenario(
        project_root=project_root,
        scenario=scenario,
        agent=ProviderFailingAgent(),
        results_dir=tmp_path,
    )

    assert report.status == "invalid"
    assert report.episode_valid is False
    assert report.failure_kind == "provider"
    assert (
        report.visible_verification.gates
        == ()
    )


def test_tool_budget_is_valid_failed_episode(
    tmp_path: Path,
) -> None:
    project_root, scenario = _load_s01()

    report = run_scenario(
        project_root=project_root,
        scenario=scenario,
        agent=BudgetFailingAgent(),
        results_dir=tmp_path,
    )

    assert report.status == "failed"
    assert report.episode_valid is True
    assert (
        report.failure_kind
        == "agent_runtime"
    )
