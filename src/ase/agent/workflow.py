from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ase.tools.repository import RepositoryTools
from ase.verifier.models import GateResult, VerificationReport
from ase.verifier.patching import apply_unified_diff
from ase.verifier.policy import PatchPolicy, check_patch_policy
from ase.verifier.runner import verify_visible

from .base import EngineeringAgent
from .models import Investigation, PatchProposal

Verifier = Callable[[Path], VerificationReport]


@dataclass(frozen=True, slots=True)
class WorkflowResult:
    investigation: Investigation
    proposal: PatchProposal
    policy_gate: GateResult
    verification: VerificationReport
    status: str
    error: str = ""


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
        proposal = self._agent.propose_patch(ticket, investigation, tools)

        policy_gate = check_patch_policy(proposal.diff, policy)
        if not policy_gate.passed:
            return WorkflowResult(
                investigation=investigation,
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
                proposal=proposal,
                policy_gate=policy_gate,
                verification=VerificationReport(gates=()),
                status="failed",
                error=f"patch_apply: {exc}",
            )

        verification = self._verifier(workspace)
        return WorkflowResult(
            investigation=investigation,
            proposal=proposal,
            policy_gate=policy_gate,
            verification=verification,
            status="passed" if verification.passed else "failed",
            error="" if verification.passed else "visible verification failed",
        )
