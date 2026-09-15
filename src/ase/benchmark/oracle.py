from pathlib import Path
import os
import subprocess
import sys
import time

from ase.verifier.models import GateResult


def run_hidden_oracle(workspace: Path, oracle_tests: Path) -> GateResult:
    started = time.perf_counter()
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(workspace)

    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", str(oracle_tests)],
        cwd=workspace,
        env=environment,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    details = (
        completed.stdout
        if completed.returncode == 0
        else f"{completed.stdout}\n{completed.stderr}"
    )
    return GateResult(
        name="hidden_oracle",
        passed=completed.returncode == 0,
        details=details[-12_000:].strip(),
        duration_ms=(time.perf_counter() - started) * 1000,
    )
