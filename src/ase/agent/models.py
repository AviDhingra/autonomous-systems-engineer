from dataclasses import dataclass

from ase.tools.models import FileSlice, SearchMatch


@dataclass(frozen=True, slots=True)
class Investigation:
    searches: tuple[SearchMatch, ...]
    files: tuple[FileSlice, ...]
    summary: str


@dataclass(frozen=True, slots=True)
class PatchProposal:
    summary: str
    diff: str
