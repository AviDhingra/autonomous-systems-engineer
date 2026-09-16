import pytest
from pydantic import ValidationError

from ase.agent.schemas import DiagnosisOutput


def test_diagnosis_rejects_invalid_confidence() -> None:
    with pytest.raises(ValidationError):
        DiagnosisOutput(
            root_cause="example",
            evidence=[],
            affected_files=[],
            proposed_change="example",
            confidence=1.5,
        )
