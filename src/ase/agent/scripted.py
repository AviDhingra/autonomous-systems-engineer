from ase.tools.repository import RepositoryTools

from .models import Investigation, PatchProposal


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
        tools: RepositoryTools,
    ) -> PatchProposal:
        del ticket, investigation, tools
        return PatchProposal(
            summary="Restore idempotent telemetry retry handling.",
            diff=self._patch,
        )
