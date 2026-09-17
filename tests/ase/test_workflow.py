from collections.abc import Callable
from pathlib import Path
import subprocess

from ase.agent.models import Diagnosis, Investigation, PatchProposal
from ase.agent.workflow import VerifiedRepairWorkflow
from ase.tools.repository import RepositoryTools
from ase.verifier.models import GateResult, VerificationReport
from ase.verifier.policy import PatchPolicy


APP_FILE = Path("target/fleetops/app/example.py")


FIRST_PATCH = """\
diff --git a/target/fleetops/app/example.py b/target/fleetops/app/example.py
--- a/target/fleetops/app/example.py
+++ b/target/fleetops/app/example.py
@@ -1 +1 @@
-VALUE = 1
+VALUE = 2
"""


REPAIR_PATCH = """\
diff --git a/target/fleetops/app/example.py b/target/fleetops/app/example.py
--- a/target/fleetops/app/example.py
+++ b/target/fleetops/app/example.py
@@ -1 +1 @@
-VALUE = 2
+VALUE = 3
"""


FORBIDDEN_PATCH = """\
diff --git a/tests/forbidden.py b/tests/forbidden.py
--- /dev/null
+++ b/tests/forbidden.py
@@ -0,0 +1 @@
+SHOULD_NOT_EXIST = True
"""


class FakeAgent:
    """Deterministic test double for the Part 13 workflow."""

    def __init__(
        self,
        *,
        proposal: PatchProposal,
        repair: PatchProposal | None = None,
    ) -> None:
        self._proposal = proposal
        self._repair = repair

        self.investigate_calls = 0
        self.diagnose_calls = 0
        self.propose_calls = 0
        self.repair_calls = 0

    def investigate(
        self,
        ticket: str,
        tools: RepositoryTools,
    ) -> Investigation:
        del ticket, tools
        self.investigate_calls += 1

        return Investigation(
            searches=(),
            files=(),
            summary="Deterministic test investigation.",
        )

    def diagnose(
        self,
        ticket: str,
        investigation: Investigation,
        tools: RepositoryTools,
    ) -> Diagnosis:
        del ticket, investigation, tools
        self.diagnose_calls += 1

        return Diagnosis(
            root_cause="The test value is incorrect.",
            evidence_paths=(str(APP_FILE),),
            affected_files=(str(APP_FILE),),
            proposed_change="Update the value.",
            confidence=1.0,
        )

    def propose_patch(
        self,
        ticket: str,
        investigation: Investigation,
        diagnosis: Diagnosis,
        tools: RepositoryTools,
    ) -> PatchProposal:
        del ticket, investigation, diagnosis, tools
        self.propose_calls += 1
        return self._proposal

    def repair_patch(
        self,
        ticket: str,
        investigation: Investigation,
        diagnosis: Diagnosis,
        previous: PatchProposal,
        verification: VerificationReport,
        tools: RepositoryTools,
    ) -> PatchProposal:
        del ticket, investigation, diagnosis, previous, tools
        self.repair_calls += 1

        assert verification.passed is False

        if self._repair is None:
            raise AssertionError(
                "repair_patch was called, but this FakeAgent "
                "was not configured with a repair proposal"
            )

        return self._repair


def _verification_report(
    *,
    passed: bool,
    name: str = "fake_visible",
    details: str | None = None,
) -> VerificationReport:
    return VerificationReport(
        gates=(
            GateResult(
                name=name,
                passed=passed,
                details=(
                    details
                    if details is not None
                    else ("ok" if passed else "visible check failed")
                ),
            ),
        )
    )


def _init_workspace(tmp_path: Path) -> Path:
    """Create the smallest Git workspace the real patch applier can modify."""

    workspace = tmp_path / "workspace"
    app_file = workspace / APP_FILE

    app_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    app_file.write_text(
        "VALUE = 1\n",
        encoding="utf-8",
    )

    subprocess.run(
        ["git", "init", "-q"],
        cwd=workspace,
        check=True,
    )

    return workspace


def test_first_pass_success(
    tmp_path: Path,
) -> None:
    workspace = _init_workspace(tmp_path)

    agent = FakeAgent(
        proposal=PatchProposal(
            summary="Change VALUE from 1 to 2.",
            diff=FIRST_PATCH,
        )
    )

    verifier_calls = 0

    def passing_verifier(
        _: Path,
    ) -> VerificationReport:
        nonlocal verifier_calls
        verifier_calls += 1
        return _verification_report(
            passed=True,
        )

    workflow = VerifiedRepairWorkflow(
        agent,
        verifier=passing_verifier,
    )

    result = workflow.run(
        ticket="Update the test value.",
        workspace=workspace,
        policy=PatchPolicy(),
    )

    assert result.status == "passed"
    assert result.error == ""
    assert result.attempts == 1

    assert result.diagnosis.root_cause == (
        "The test value is incorrect."
    )
    assert result.policy_gate.passed is True
    assert result.verification.passed is True

    assert result.repair_proposal is None
    assert result.repair_policy_gate is None

    assert (workspace / APP_FILE).read_text(
        encoding="utf-8"
    ) == "VALUE = 2\n"

    assert verifier_calls == 1
    assert agent.investigate_calls == 1
    assert agent.diagnose_calls == 1
    assert agent.propose_calls == 1
    assert agent.repair_calls == 0


def test_visible_failure_then_successful_repair(
    tmp_path: Path,
) -> None:
    workspace = _init_workspace(tmp_path)

    agent = FakeAgent(
        proposal=PatchProposal(
            summary="First attempt.",
            diff=FIRST_PATCH,
        ),
        repair=PatchProposal(
            summary="Incremental repair.",
            diff=REPAIR_PATCH,
        ),
    )

    reports = iter(
        (
            _verification_report(
                passed=False,
                details="first attempt failed",
            ),
            _verification_report(
                passed=True,
            ),
        )
    )
    verifier_calls = 0

    def sequenced_verifier(
        _: Path,
    ) -> VerificationReport:
        nonlocal verifier_calls
        verifier_calls += 1
        return next(reports)

    workflow = VerifiedRepairWorkflow(
        agent,
        verifier=sequenced_verifier,
    )

    result = workflow.run(
        ticket="Update the test value.",
        workspace=workspace,
        policy=PatchPolicy(),
    )

    assert result.status == "passed"
    assert result.error == ""
    assert result.attempts == 2

    assert result.verification.passed is True
    assert result.repair_proposal is not None
    assert result.repair_proposal.diff == REPAIR_PATCH
    assert result.repair_policy_gate is not None
    assert result.repair_policy_gate.passed is True

    assert (workspace / APP_FILE).read_text(
        encoding="utf-8"
    ) == "VALUE = 3\n"

    assert verifier_calls == 2
    assert agent.repair_calls == 1


def test_repair_can_still_fail_visible_verification(
    tmp_path: Path,
) -> None:
    workspace = _init_workspace(tmp_path)

    agent = FakeAgent(
        proposal=PatchProposal(
            summary="First attempt.",
            diff=FIRST_PATCH,
        ),
        repair=PatchProposal(
            summary="Second attempt.",
            diff=REPAIR_PATCH,
        ),
    )

    reports = iter(
        (
            _verification_report(
                passed=False,
                details="first attempt failed",
            ),
            _verification_report(
                passed=False,
                details="repair also failed",
            ),
        )
    )

    def failing_verifier(
        _: Path,
    ) -> VerificationReport:
        return next(reports)

    workflow = VerifiedRepairWorkflow(
        agent,
        verifier=failing_verifier,
    )

    result = workflow.run(
        ticket="Update the test value.",
        workspace=workspace,
        policy=PatchPolicy(),
    )

    assert result.status == "failed"
    assert result.error == "visible verification failed"
    assert result.attempts == 2

    assert result.verification.passed is False
    assert result.verification.gates[0].details == (
        "repair also failed"
    )

    assert result.repair_proposal is not None
    assert result.repair_policy_gate is not None
    assert result.repair_policy_gate.passed is True

    assert (workspace / APP_FILE).read_text(
        encoding="utf-8"
    ) == "VALUE = 3\n"

    assert agent.repair_calls == 1


def test_policy_rejection_does_not_mutate_workspace(
    tmp_path: Path,
) -> None:
    workspace = _init_workspace(tmp_path)

    agent = FakeAgent(
        proposal=PatchProposal(
            summary="Attempt to edit a forbidden path.",
            diff=FORBIDDEN_PATCH,
        )
    )

    verifier_called = False

    def verifier_that_must_not_run(
        _: Path,
    ) -> VerificationReport:
        nonlocal verifier_called
        verifier_called = True
        return _verification_report(
            passed=True,
        )

    workflow = VerifiedRepairWorkflow(
        agent,
        verifier=verifier_that_must_not_run,
    )

    original = (workspace / APP_FILE).read_text(
        encoding="utf-8"
    )

    result = workflow.run(
        ticket="Try an unsafe change.",
        workspace=workspace,
        policy=PatchPolicy(),
    )

    assert result.status == "failed"
    assert result.policy_gate.passed is False
    assert "forbidden path" in result.policy_gate.details
    assert result.verification.gates == ()
    assert result.attempts == 1

    assert (workspace / APP_FILE).read_text(
        encoding="utf-8"
    ) == original
    assert not (workspace / "tests" / "forbidden.py").exists()

    assert verifier_called is False
    assert agent.repair_calls == 0