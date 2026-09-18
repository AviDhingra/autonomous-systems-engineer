from pathlib import Path
import json

from ase.observability.trace import (
    JsonlTraceWriter,
)


def test_trace_writer_appends_json_lines(
    tmp_path: Path,
) -> None:
    path = tmp_path / "trace.jsonl"
    writer = JsonlTraceWriter(path)

    writer.write(
        "run_started",
        {"scenario_id": "S01"},
    )
    writer.write(
        "verification_result",
        {"passed": True},
    )

    lines = path.read_text(
        encoding="utf-8",
    ).splitlines()

    assert len(lines) == 2

    first = json.loads(lines[0])
    second = json.loads(lines[1])

    assert first["kind"] == "run_started"
    assert first["data"]["scenario_id"] == "S01"

    assert (
        second["kind"]
        == "verification_result"
    )
    assert second["data"]["passed"] is True
