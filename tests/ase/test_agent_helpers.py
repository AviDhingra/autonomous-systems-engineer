from pathlib import Path

import pytest

from ase.agent import _run_tool


def _write(repo_root: Path, relative_path: str, text: str) -> None:
    path = repo_root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_run_tool_reads_file(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "target/fleetops/app/example.py",
        "VALUE = 42\n",
    )

    result = _run_tool(
        tmp_path,
        "read_file",
        {"relative_path": "target/fleetops/app/example.py"},
    )

    assert result == "VALUE = 42\n"


def test_run_tool_searches_code(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "target/fleetops/app/example.py",
        "request_id = 'abc'\n",
    )

    result = _run_tool(
        tmp_path,
        "search_code",
        {"query": "request_id"},
    )

    assert "target/fleetops/app/example.py:1:" in result
    assert "request_id = 'abc'" in result


def test_run_tool_reports_no_matches(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "target/fleetops/app/example.py",
        "VALUE = 42\n",
    )

    result = _run_tool(
        tmp_path,
        "search_code",
        {"query": "missing_symbol"},
    )

    assert result == "No matches found."


def test_run_tool_rejects_non_string_argument(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="must be a string"):
        _run_tool(
            tmp_path,
            "search_code",
            {"query": 123},
        )

def test_run_tool_rejects_unknown_tool(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown tool"):
        _run_tool(
            tmp_path,
            "delete_repository",
            {},
        )
