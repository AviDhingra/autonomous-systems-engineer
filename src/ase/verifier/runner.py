from pathlib import Path

from ase.tools.checks import (
    run_git_diff_check,
    run_mypy,
    run_ruff,
    run_visible_tests,
)
from ase.tools.models import ProcessResult

from .models import GateResult, VerificationReport


def _gate_from_process(result: ProcessResult) -> GateResult:
    details = result.stdout if result.ok else f"{result.stdout}\n{result.stderr}"
    return GateResult(
        name=result.command_name,
        passed=result.ok,
        details=details[-12_000:].strip(),
        duration_ms=result.duration_ms,
    )


def verify_visible(workspace: Path) -> VerificationReport:
    results = (
        run_visible_tests(workspace),
        run_ruff(workspace),
        run_mypy(workspace),
        run_git_diff_check(workspace),
    )
    return VerificationReport(gates=tuple(_gate_from_process(result) for result in results))
