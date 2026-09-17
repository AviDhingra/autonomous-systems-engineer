from ase.tools.repository import RepositoryTools

from ase.verifier.models import (
    VerificationReport,
)

from .models import (
    Diagnosis,
    Investigation,
    PatchProposal,
)



class ScriptedEngineeringAgent:
    """Deterministic teaching double used to test the workflow before any LLM exists."""

    def __init__(self, patch: str) -> None:
        self._patch = patch

    def investigate(self, ticket: str, tools: RepositoryTools) -> Investigation:
        searches = tuple(tools.search_text("get_by_request", limit=20))
        telemetry_service = tools.read_file(
            "target/fleetops/app/services/telemetry.py",
            start_line=1,
            end_line=160,
        )
        return Investigation(
            searches=searches,
            files=(telemetry_service,),
            summary=(
                "The scripted agent inspected the telemetry service and request-id lookup "
                "locations. This is deterministic plumbing, not AI reasoning."
            ),
        )

    def propose_patch(
        self,
        ticket: str,
        investigation: Investigation,
        diagnosis: Diagnosis,
        tools: RepositoryTools,
    ) -> PatchProposal:
        del ticket, investigation, tools, diagnosis
        return PatchProposal(
            summary="Restore idempotent telemetry retry handling.",
            diff=self._patch,
        )


    def diagnose(
        self,
        ticket: str,
        investigation: Investigation,
        tools: RepositoryTools,
    ) -> Diagnosis:
        del ticket, investigation, tools

        return Diagnosis(
            root_cause=(
                "Telemetry ingestion is missing "
                "the request-id idempotency check."
            ),
            evidence_paths=(
                "target/fleetops/app/services/"
                "telemetry.py",
            ),
            affected_files=(
                "target/fleetops/app/services/"
                "telemetry.py",
            ),
            proposed_change=(
                "Return the existing telemetry "
                "record before creating a new one."
            ),
            confidence=1.0,
        )


    def repair_patch(
        self,
        ticket: str,
        investigation: Investigation,
        diagnosis: Diagnosis,
        previous: PatchProposal,
        verification: VerificationReport,
        tools: RepositoryTools,
    ) -> PatchProposal:
        del (
            ticket,
            investigation,
            diagnosis,
            previous,
            verification,
            tools,
        )
        raise RuntimeError(
            "scripted reference repair should "
            "not require a second attempt"
        )
