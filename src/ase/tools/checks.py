from pathlib import Path
import subprocess
import sys
import time

from .models import ProcessResult


def _text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value


def _run_fixed(
    *,
    name: str,
    argv: list[str],
    cwd: Path,
    timeout_seconds: int = 90,
) -> ProcessResult:
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        return ProcessResult(
            command_name=name,
            returncode=completed.returncode,
            stdout=completed.stdout[-12_000:],
            stderr=completed.stderr[-12_000:],
            duration_ms=(time.perf_counter() - started) * 1000,
        )
    except subprocess.TimeoutExpired as exc:
        return ProcessResult(
            command_name=name,
            returncode=124,
            stdout=_text(exc.stdout)[-12_000:],
            stderr=(
                f"timed out after {timeout_seconds} seconds\n{_text(exc.stderr)}"
            )[-12_000:],
            duration_ms=(time.perf_counter() - started) * 1000,
        )


def run_visible_tests(workspace: Path) -> ProcessResult:
    return _run_fixed(
        name="pytest",
        argv=[sys.executable, "-m", "pytest", "-q", "target/fleetops/tests"],
        cwd=workspace,
    )


def run_ruff(workspace: Path) -> ProcessResult:
    return _run_fixed(
        name="ruff",
        argv=[sys.executable, "-m", "ruff", "check", "target/fleetops"],
        cwd=workspace,
    )


def run_mypy(workspace: Path) -> ProcessResult:
    return _run_fixed(
        name="mypy",
        argv=[sys.executable, "-m", "mypy", "target/fleetops"],
        cwd=workspace,
    )


def run_git_diff_check(workspace: Path) -> ProcessResult:
    return _run_fixed(
        name="git_diff_check",
        argv=["git", "diff", "--check"],
        cwd=workspace,
    )
