import sys
from pathlib import Path

from ase.verify import CheckResult, VerificationResult, _run_check


def test_run_check_captures_success(tmp_path: Path) -> None:
    result = _run_check(
        tmp_path,
        "demo-success",
        [sys.executable, "-c", "print('hello from child')"],
        timeout_seconds=10,
    )

    assert result.name == "demo-success"
    assert result.passed is True
    assert result.returncode == 0
    assert result.stdout.strip() == "hello from child"
    assert result.stderr == ""


def test_run_check_captures_failure_without_raising(tmp_path: Path) -> None:
    result = _run_check(
        tmp_path,
        "demo-failure",
        [
            sys.executable,
            "-c",
            "import sys; print('broken', file=sys.stderr); raise SystemExit(3)",
        ],
        timeout_seconds=10,
    )

    assert result.passed is False
    assert result.returncode == 3
    assert result.stdout == ""
    assert result.stderr.strip() == "broken"


def test_verification_result_requires_every_check_to_pass() -> None:
    passing = CheckResult(
        name="passing",
        command=["demo"],
        returncode=0,
        stdout="",
        stderr="",
    )
    failing = CheckResult(
        name="failing",
        command=["demo"],
        returncode=1,
        stdout="",
        stderr="",
    )

    assert VerificationResult(checks=[passing]).passed is True
    assert VerificationResult(checks=[passing, failing]).passed is False


def test_empty_verification_does_not_pass() -> None:
    assert VerificationResult(checks=[]).passed is False
