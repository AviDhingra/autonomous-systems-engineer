import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

CHECK_TIMEOUT_SECONDS = 120

@dataclass
class CheckResult:
    name: str
    command: list[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def passed(self) -> bool:
        return self.returncode == 0

@dataclass
class VerificationResult:
    checks: list[CheckResult]

    @property
    def passed(self) -> bool:
        if not self.checks:
            return False
        return all(check.passed for check in self.checks)


def _run_check(
    repo_root: Path,
    name: str,
    command: list[str],
    *,
    timeout_seconds: int = CHECK_TIMEOUT_SECONDS,
) -> CheckResult:
    completed = subprocess.run(
        command,
        cwd=repo_root.resolve(),
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )

    return CheckResult(
        name=name,
        command=command,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def verify_repository(repo_root: Path) -> VerificationResult:
    checks: list[CheckResult] = []

    checks.append(
        _run_check(
            repo_root,
            "pytest",
            [sys.executable, "-m", "pytest", "-q"],
        )
    )
    checks.append(
        _run_check(
            repo_root,
            "ruff",
            [
                sys.executable,
                "-m",
                "ruff",
                "check",
                "src/ase",
                "tests/ase",
                "target/fleetops",
            ],
        )
    )
    checks.append(
        _run_check(
            repo_root,
            "mypy",
            [sys.executable, "-m", "mypy", "src/ase", "target/fleetops"],
        )
    )

    return VerificationResult(checks=checks)
