from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FileSlice:
    path: str
    start_line: int
    end_line: int
    content: str


@dataclass(frozen=True, slots=True)
class SearchMatch:
    path: str
    line: int
    text: str


@dataclass(frozen=True, slots=True)
class ProcessResult:
    command_name: str
    returncode: int
    stdout: str
    stderr: str
    duration_ms: float

    @property
    def ok(self) -> bool:
        return self.returncode == 0
