from pathlib import Path

from ase.agent.scripted import ScriptedEngineeringAgent
from ase.benchmark.runner import run_scenario
from ase.benchmark.scenario import Scenario
from ase.verifier.models import GateResult, VerificationReport


def test_s01_runs_end_to_end_with_scripted_agent(tmp_path: Path) -> None:
    project_root = Path.cwd()
    scenario = Scenario.load(project_root / "scenarios/S01-duplicate-telemetry")
    agent = ScriptedEngineeringAgent(scenario.solution_patch)

    def fake_visible_verifier(_: Path) -> VerificationReport:
        return VerificationReport(
            gates=(GateResult(name="fake_visible", passed=True, details="ok"),)
        )

    report = run_scenario(
        project_root=project_root,
        scenario=scenario,
        agent=agent,
        results_dir=tmp_path,
        verifier=fake_visible_verifier,
    )

    assert report.status == "passed"
    assert report.pre_repair_oracle.passed is False
    assert report.post_repair_oracle.passed is True
    assert (tmp_path / "S01.json").is_file()
