from pathlib import Path

from ase.benchmark.oracle import run_hidden_oracle
from ase.benchmark.scenario import Scenario
from ase.benchmark.workspace import isolated_workspace
from ase.verifier.patching import apply_unified_diff


def test_s01_oracle_fails_for_seeded_bug_and_passes_after_solution() -> None:
    project_root = Path.cwd()
    scenario = Scenario.load(project_root / "scenarios/S01-duplicate-telemetry")

    with isolated_workspace(project_root) as workspace:
        assert not (workspace / "scenarios").exists()

        apply_unified_diff(workspace, scenario.bug_patch)
        broken = run_hidden_oracle(workspace, scenario.oracle_tests)
        assert broken.passed is False

        apply_unified_diff(workspace, scenario.solution_patch)
        repaired = run_hidden_oracle(workspace, scenario.oracle_tests)
        assert repaired.passed is True
