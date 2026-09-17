from ase.agent.models import Investigation
from ase.agent.prompts import (
    DIAGNOSIS_SYSTEM_PROMPT,
    INVESTIGATION_SYSTEM_PROMPT,
    PATCH_SYSTEM_PROMPT,
    REPAIR_SYSTEM_PROMPT,
    investigation_context,
    verification_context,
)
from ase.tools.models import FileSlice
from ase.verifier.models import GateResult, VerificationReport


def test_system_prompts_keep_each_stage_narrow() -> None:
    assert "read-only tools" in INVESTIGATION_SYSTEM_PROMPT
    assert "Do not propose a patch yet" in INVESTIGATION_SYSTEM_PROMPT

    assert "structured diagnosis" in DIAGNOSIS_SYSTEM_PROMPT
    assert "evidence" in DIAGNOSIS_SYSTEM_PROMPT

    assert "valid unified diff" in PATCH_SYSTEM_PROMPT
    assert "Do not edit tests" in PATCH_SYSTEM_PROMPT
    assert "Keep the change minimal" in PATCH_SYSTEM_PROMPT

    assert "verification" in REPAIR_SYSTEM_PROMPT
    assert "incremental unified diff" in REPAIR_SYSTEM_PROMPT
    assert "Do not edit tests" in REPAIR_SYSTEM_PROMPT


def test_investigation_context_contains_ticket_summary_and_file_evidence() -> None:
    investigation = Investigation(
        searches=(),
        files=(
            FileSlice(
                path="target/fleetops/app/services/telemetry.py",
                start_line=10,
                end_line=14,
                content=(
                    "def ingest_telemetry(...):\n"
                    "    existing = repository.get_by_request(...)\n"
                    "    return existing\n"
                ),
            ),
        ),
        summary="The telemetry ingestion path appears to handle request IDs.",
    )

    context = investigation_context(
        "Duplicate telemetry requests must be idempotent.",
        investigation,
    )

    assert "ENGINEERING TICKET:" in context
    assert "Duplicate telemetry requests must be idempotent." in context

    assert "INVESTIGATION SUMMARY:" in context
    assert "The telemetry ingestion path appears to handle request IDs." in context

    assert "FILES READ:" in context
    assert "FILE: target/fleetops/app/services/telemetry.py" in context
    assert "LINES: 10-14" in context
    assert "repository.get_by_request" in context


def test_investigation_context_includes_multiple_files_in_order() -> None:
    investigation = Investigation(
        searches=(),
        files=(
            FileSlice(
                path="first.py",
                start_line=1,
                end_line=2,
                content="FIRST_FILE_CONTENT",
            ),
            FileSlice(
                path="second.py",
                start_line=20,
                end_line=25,
                content="SECOND_FILE_CONTENT",
            ),
        ),
        summary="Two files were relevant.",
    )

    context = investigation_context(
        "Investigate the defect.",
        investigation,
    )

    assert context.index("FILE: first.py") < context.index("FILE: second.py")
    assert "LINES: 1-2" in context
    assert "LINES: 20-25" in context
    assert "FIRST_FILE_CONTENT" in context
    assert "SECOND_FILE_CONTENT" in context


def test_investigation_context_handles_no_files() -> None:
    investigation = Investigation(
        searches=(),
        files=(),
        summary="No file was read yet.",
    )

    context = investigation_context(
        "Investigate the defect.",
        investigation,
    )

    assert "ENGINEERING TICKET:" in context
    assert "INVESTIGATION SUMMARY:" in context
    assert "FILES READ:" in context
    assert "No file was read yet." in context


def test_verification_context_contains_only_failed_gates() -> None:
    report = VerificationReport(
        gates=(
            GateResult(
                name="pytest",
                passed=True,
                details="27 tests passed",
                duration_ms=120.0,
            ),
            GateResult(
                name="mypy",
                passed=False,
                details="Argument has incompatible type",
                duration_ms=85.0,
            ),
            GateResult(
                name="ruff",
                passed=False,
                details="I001 import block is un-sorted",
                duration_ms=40.0,
            ),
        )
    )

    context = verification_context(report)

    assert "GATE: mypy" in context
    assert "Argument has incompatible type" in context
    assert "GATE: ruff" in context
    assert "I001 import block is un-sorted" in context

    assert "GATE: pytest" not in context
    assert "27 tests passed" not in context

    assert context.count("STATUS: FAILED") == 2


def test_verification_context_is_empty_when_every_gate_passes() -> None:
    report = VerificationReport(
        gates=(
            GateResult(
                name="pytest",
                passed=True,
                details="27 tests passed",
                duration_ms=120.0,
            ),
            GateResult(
                name="mypy",
                passed=True,
                details="Success: no issues found",
                duration_ms=85.0,
            ),
        )
    )

    assert verification_context(report) == ""