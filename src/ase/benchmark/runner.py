from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
import json
import time

from ase.agent.base import EngineeringAgent
from ase.agent.workflow import VerifiedRepairWorkflow
from ase.verifier.models import GateResult, VerificationReport
from ase.verifier.patching import apply_unified_diff
from ase.verifier.runner import verify_visible

from .oracle import run_hidden_oracle
from .scenario import Scenario
from .workspace import isolated_workspace

Verifier = Callable[[Path], VerificationReport]


@dataclass(frozen=True, slots=True)
class BenchmarkRunReport:
    scenario_id: str
    status: str
    duration_seconds: float
    pre_repair_oracle: GateResult
    post_repair_oracle: GateResult
    visible_verification: VerificationReport
    visible_verification_passed: bool
    error: str


def run_scenario(
    *,
    project_root: Path,
    scenario: Scenario,
    agent: EngineeringAgent,
    results_dir: Path,
    verifier: Verifier = verify_visible,
) -> BenchmarkRunReport:
    with isolated_workspace(project_root) as workspace:
        apply_unified_diff(workspace, scenario.bug_patch)

        pre_oracle = run_hidden_oracle(workspace, scenario.oracle_tests)
        if pre_oracle.passed:
            raise RuntimeError(
                "scenario sanity check failed: hidden oracle passes before repair"
            )

        workflow = VerifiedRepairWorkflow(agent, verifier=verifier)
        started = time.perf_counter()
        workflow_result = workflow.run(
            ticket=scenario.ticket,
            workspace=workspace,
            policy=scenario.patch_policy,
        )
        elapsed = time.perf_counter() - started

        post_oracle = run_hidden_oracle(workspace, scenario.oracle_tests)
        passed = workflow_result.status == "passed" and post_oracle.passed
        report = BenchmarkRunReport(
            scenario_id=scenario.config.scenario_id,
            status="passed" if passed else "failed",
            duration_seconds=elapsed,
            pre_repair_oracle=pre_oracle,
            post_repair_oracle=post_oracle,
            visible_verification=workflow_result.verification,
            visible_verification_passed=workflow_result.verification.passed,
            error=workflow_result.error,
        )

        results_dir.mkdir(parents=True, exist_ok=True)
        output_path = results_dir / f"{scenario.config.scenario_id}.json"
        output_path.write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")
        return report
