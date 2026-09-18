from dataclasses import (
    asdict,
    dataclass,
)
from datetime import (
    UTC,
    datetime,
)
from pathlib import Path
import json


@dataclass(frozen=True, slots=True)
class TraceEvent:
    timestamp: str
    kind: str
    data: dict[str, object]


class JsonlTraceWriter:
    def __init__(
        self,
        path: Path,
    ) -> None:
        self._path = path

        self._path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

    @property
    def path(self) -> Path:
        return self._path

    def write(
        self,
        kind: str,
        data: dict[str, object],
    ) -> None:
        event = TraceEvent(
            timestamp=(
                datetime.now(UTC)
                .isoformat()
            ),
            kind=kind,
            data=data,
        )

        with self._path.open(
            "a",
            encoding="utf-8",
        ) as handle:
            handle.write(
                json.dumps(
                    asdict(event),
                    ensure_ascii=False,
                )
            )
            handle.write("\n")
