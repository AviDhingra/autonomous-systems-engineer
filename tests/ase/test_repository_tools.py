from pathlib import Path

import pytest

from ase.tools.repository import RepositoryTools


def test_read_file_returns_requested_slice(tmp_path: Path) -> None:
    (tmp_path / "example.py").write_text("one\ntwo\nthree\n", encoding="utf-8")
    tools = RepositoryTools(tmp_path)

    result = tools.read_file("example.py", start_line=2, end_line=3)

    assert result.start_line == 2
    assert result.end_line == 3
    assert result.content == "two\nthree"


def test_read_file_rejects_path_escape(tmp_path: Path) -> None:
    tools = RepositoryTools(tmp_path)

    with pytest.raises(ValueError, match="escapes workspace"):
        tools.read_file("../secret.txt")


def test_search_text_returns_matching_lines(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("alpha\nget_by_request()\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("nothing\n", encoding="utf-8")
    tools = RepositoryTools(tmp_path)

    matches = tools.search_text("get_by_request")

    assert len(matches) == 1
    assert matches[0].path == "a.py"
    assert matches[0].line == 2
