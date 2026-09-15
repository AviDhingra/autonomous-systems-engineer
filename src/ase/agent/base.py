from typing import Protocol

from ase.tools.repository import RepositoryTools

from .models import Investigation, PatchProposal


class EngineeringAgent(Protocol):
    def investigate(self, ticket: str, tools: RepositoryTools) -> Investigation: ...

    def propose_patch(
        self,
        ticket: str,
        investigation: Investigation,
        tools: RepositoryTools,
    ) -> PatchProposal: ...
