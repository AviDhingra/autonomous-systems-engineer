from pydantic import BaseModel, Field


class EvidenceItem(BaseModel):
    path: str = Field(min_length=1)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    observation: str = Field(min_length=1)


class DiagnosisOutput(BaseModel):
    root_cause: str = Field(min_length=1)
    evidence: list[EvidenceItem]
    affected_files: list[str]
    proposed_change: str = Field(min_length=1)
    confidence: float = Field(
        ge=0.0,
        le=1.0,
    )


class PatchOutput(BaseModel):
    summary: str = Field(min_length=1)
    diff: str = Field(min_length=1)


class RepairOutput(BaseModel):
    summary: str = Field(min_length=1)
    diff: str = Field(min_length=1)
    addressed_failures: list[str]
