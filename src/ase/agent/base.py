from typing import Protocol

from ase.tools.repository import RepositoryTools
from ase.verifier.models import VerificationReport

from .models import (
    Diagnosis,
    Investigation,
    PatchProposal,
)


class EngineeringAgent(Protocol):
    def investigate(self, ticket: str, tools: RepositoryTools) -> Investigation: ...

    def diagnose(
        self,
        ticket: str,
        investigation: Investigation,
        tools: RepositoryTools,
    ) -> Diagnosis:
        ...

    def propose_patch(
        self,
        ticket: str,
        investigation: Investigation,
        diagnosis: Diagnosis,
        tools: RepositoryTools,
    ) -> PatchProposal: ...

    def repair_patch(
        self,
        ticket: str,
        investigation: Investigation,
        diagnosis: Diagnosis,
        previous: PatchProposal,
        verification: VerificationReport,
        tools: RepositoryTools,
    ) -> PatchProposal:
        ...
