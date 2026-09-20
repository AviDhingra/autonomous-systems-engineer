from pathlib import Path

import pytest

from ase.tools import read_file, search_code

FLEETOPS_ROOT = Path("target/fleetops")

def _write(repo_root: Path, relative_path: str, content: str) -> None:
    path = repo_root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_read_file_returns_utf8_text(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "target/fleetops/app/example.py",
        'MESSAGE = "Grüße"\n',
    )

    content = read_file(tmp_path, "target/fleetops/app/example.py")

    assert content == 'MESSAGE = "Grüße"\n'


def test_read_file_rejects_path_outside_fleetops(tmp_path: Path) -> None:
    _write(tmp_path, "outside.py", "SECRET = True\n")

    with pytest.raises(ValueError, match="path must stay inside"):
        read_file(tmp_path, "outside.py")


def test_read_file_rejects_directory(tmp_path: Path) -> None:
    (tmp_path / "target/fleetops/app").mkdir(parents=True)

    with pytest.raises(ValueError, match="not a file"):
        read_file(tmp_path, "target/fleetops/app")


def test_search_code_returns_matching_lines(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "target/fleetops/app/service.py",
        "first line\nget_by_request(device_id, request_id)\n",
    )
    _write(
        tmp_path,
        "target/fleetops/tests/test_service.py",
        "assert get_by_request is not None\n",
    )

    matches = search_code(tmp_path, "get_by_request")

    assert matches == [
        "target/fleetops/app/service.py:2: get_by_request(device_id, request_id)",
        "target/fleetops/tests/test_service.py:1: assert get_by_request is not None",
    ]


def test_search_code_rejects_blank_query(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="query must not be empty"):
        search_code(tmp_path, "   ")
