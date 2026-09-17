from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ase.tools.repository import RepositoryTools
from ase.verifier.models import GateResult, VerificationReport
from ase.verifier.patching import apply_unified_diff
from ase.verifier.policy import PatchPolicy, check_patch_policy
from ase.verifier.runner import verify_visible

from .base import EngineeringAgent
from .models import Investigation, PatchProposal, Diagnosis

Verifier = Callable[[Path], VerificationReport]


@dataclass(frozen=True, slots=True)
class WorkflowResult:
    investigation: Investigation
    diagnosis: Diagnosis
    proposal: PatchProposal
    policy_gate: GateResult
    verification: VerificationReport
    status: str
    error: str = ""
    attempts: int = 1
    repair_proposal: PatchProposal | None = None
    repair_policy_gate: GateResult | None = None


class VerifiedRepairWorkflow:
    """One deterministic repair attempt: investigate, propose, gate, apply, verify."""

    def __init__(
        self,
        agent: EngineeringAgent,
        *,
        verifier: Verifier = verify_visible,
    ) -> None:
        self._agent = agent
        self._verifier = verifier

    def run(
        self,
        *,
        ticket: str,
        workspace: Path,
        policy: PatchPolicy,
    ) -> WorkflowResult:
        tools = RepositoryTools(workspace)
        investigation = self._agent.investigate(ticket, tools)

        diagnosis = self._agent.diagnose(
            ticket,
            investigation,
            tools,
        )
        
        proposal = self._agent.propose_patch(ticket, investigation, diagnosis, tools)

        policy_gate = check_patch_policy(proposal.diff, policy)

        if not policy_gate.passed:
            return WorkflowResult(
                investigation=investigation,
                diagnosis=diagnosis,
                proposal=proposal,
                policy_gate=policy_gate,
                verification=VerificationReport(gates=()),
                status="failed",
                error=policy_gate.details,
            )

        try:
            apply_unified_diff(workspace, proposal.diff)
        except (ValueError, RuntimeError) as exc:
            return WorkflowResult(
                investigation=investigation,
                diagnosis=diagnosis,
                proposal=proposal,
                policy_gate=policy_gate,
                verification=VerificationReport(gates=()),
                status="failed",
                error=f"patch_apply: {exc}",
            )

        verification = self._verifier(workspace)


        if verification.passed:
            return WorkflowResult(
                investigation=investigation,
                diagnosis=diagnosis,
                proposal=proposal,
                policy_gate=policy_gate,
                verification=verification,
                status="passed",
            )

        repair = self._agent.repair_patch(
            ticket,
            investigation,
            diagnosis,
            proposal,
            verification,
            tools,
        )

        repair_policy = check_patch_policy(
            repair.diff,
            policy,
        )

        if not repair_policy.passed:
            return WorkflowResult(
                investigation=investigation,
                diagnosis=diagnosis,
                proposal=proposal,
                policy_gate=policy_gate,
                verification=verification,
                status="failed",
                error=(
                    "repair_policy: "
                    f"{repair_policy.details}"
                ),
                attempts=2,
                repair_proposal=repair,
                repair_policy_gate=repair_policy,
            )

        try:
            apply_unified_diff(
                workspace,
                repair.diff,
            )
        except (
            ValueError,
            RuntimeError,
        ) as exc:
            return WorkflowResult(
                investigation=investigation,
                diagnosis=diagnosis,
                proposal=proposal,
                policy_gate=policy_gate,
                verification=verification,
                status="failed",
                error=(
                    "repair_patch_apply: "
                    f"{exc}"
                ),
                attempts=2,
                repair_proposal=repair,
                repair_policy_gate=repair_policy,
            )

        second_verification = (
            self._verifier(workspace)
        )

        return WorkflowResult(
            investigation=investigation,
            diagnosis=diagnosis,
            proposal=proposal,
            policy_gate=policy_gate,
            verification=second_verification,
            status=(
                "passed"
                if second_verification.passed
                else "failed"
            ),
            error=(
                ""
                if second_verification.passed
                else "visible verification failed"
            ),
            attempts=2,
            repair_proposal=repair,
            repair_policy_gate=repair_policy,
        )










        
