from pathlib import Path

import pytest

from ase.apply_fix import apply_fix
from ase.models import FixProposal


def _write(repo_root: Path, relative_path: str, content: str) -> Path:
    path = repo_root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path

def test_apply_fix_replaces_existing_application_file(tmp_path: Path) -> None:
    target = _write(
        tmp_path,
        "target/fleetops/app/example.py",
        'STATUS = "broken"\n',
    )
    proposal = FixProposal(
        file_path="target/fleetops/app/example.py",
        explanation="Restore the expected status.",
        new_content='STATUS = "healthy"\n',
    )

    old_content = apply_fix(tmp_path, proposal)

    assert old_content == 'STATUS = "broken"\n'
    assert target.read_text(encoding="utf-8") == 'STATUS = "healthy"\n'


def test_apply_fix_rejects_test_file(tmp_path: Path) -> None:
    target = _write(
        tmp_path,
        "target/fleetops/tests/test_example.py",
        "def test_example():\n    assert False\n",
    )
    original = target.read_text(encoding="utf-8")
    proposal = FixProposal(
        file_path="target/fleetops/tests/test_example.py",
        explanation="Make the test pass.",
        new_content="def test_example():\n    assert True\n",
    )

    with pytest.raises(ValueError, match="path must stay inside target/fleetops/app"):
        apply_fix(tmp_path, proposal)

    assert target.read_text(encoding="utf-8") == original

def test_apply_fix_rejects_missing_application_file(tmp_path: Path) -> None:
    (tmp_path / "target/fleetops/app").mkdir(parents=True)
    proposal = FixProposal(
        file_path="target/fleetops/app/new_file.py",
        explanation="Create a new helper.",
        new_content="VALUE = 1\n",
    )

    with pytest.raises(ValueError, match="target file does not exist"):
        apply_fix(tmp_path, proposal)

    assert not (tmp_path / "target/fleetops/app/new_file.py").exists()
