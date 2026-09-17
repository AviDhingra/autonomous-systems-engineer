from dataclasses import dataclass

from ase.tools.models import FileSlice, SearchMatch

@dataclass(frozen=True, slots=True)
class ToolEvent:
    name: str
    arguments: dict[str, object]
    success: bool
    output_preview: str

@dataclass(frozen=True, slots=True)
class Investigation:
    searches: tuple[SearchMatch, ...]
    files: tuple[FileSlice, ...]
    summary: str
    tool_events: tuple[ToolEvent, ...] = ()


@dataclass(frozen=True, slots=True)
class PatchProposal:
    summary: str
    diff: str


@dataclass(frozen=True, slots=True)
class Diagnosis:
    root_cause: str
    evidence_paths: tuple[str, ...]
    affected_files: tuple[str, ...]
    proposed_change: str
    confidence: float