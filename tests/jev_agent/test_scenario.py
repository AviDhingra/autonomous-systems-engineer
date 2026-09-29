import subprocess
from pathlib import Path

import pytest

from jev_agent.scenario import injected_bug

SCENARIO = "S99-test"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    _git(tmp_path, "config", "core.autocrlf", "false")
    target = tmp_path / "target" / "fleetops"
    target.mkdir(parents=True)
    (target / "mod.py").write_text("keep\nguard\nend\n", encoding="utf-8", newline="\n")
    scenario = tmp_path / "scenarios" / SCENARIO
    scenario.mkdir(parents=True)
    (scenario / "bug.patch").write_text(
        "--- a/target/fleetops/mod.py\n"
        "+++ b/target/fleetops/mod.py\n"
        "@@ -1,3 +1,2 @@\n"
        " keep\n"
        "-guard\n"
        " end\n",
        encoding="utf-8",
        newline="\n",
    )
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "baseline")
    return tmp_path


def test_bug_is_injected_then_baseline_restored(repo: Path) -> None:
    mod = repo / "target" / "fleetops" / "mod.py"
    with injected_bug(repo, SCENARIO):
        assert mod.read_text(encoding="utf-8") == "keep\nend\n"
        mod.write_text("agent edit\n", encoding="utf-8")
    assert mod.read_text(encoding="utf-8") == "keep\nguard\nend\n"


def test_baseline_restored_even_when_the_run_raises(repo: Path) -> None:
    mod = repo / "target" / "fleetops" / "mod.py"
    with pytest.raises(ValueError), injected_bug(repo, SCENARIO):
        raise ValueError("run blew up")
    assert mod.read_text(encoding="utf-8") == "keep\nguard\nend\n"


def test_refuses_to_start_on_a_dirty_target_tree(repo: Path) -> None:
    mod = repo / "target" / "fleetops" / "mod.py"
    mod.write_text("uncommitted\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="uncommitted"), injected_bug(repo, SCENARIO):
        pass
    assert mod.read_text(encoding="utf-8") == "uncommitted\n"


def test_crlf_patch_file_still_applies(repo: Path) -> None:
    # `core.autocrlf=true` checkouts rewrite the patch to CRLF, which plain
    # `git apply <file>` rejects as corrupt.
    patch = repo / "scenarios" / SCENARIO / "bug.patch"
    patch.write_bytes(patch.read_bytes().replace(b"\n", b"\r\n"))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "crlf patch")
    mod = repo / "target" / "fleetops" / "mod.py"

    with injected_bug(repo, SCENARIO):
        assert mod.read_text(encoding="utf-8") == "keep\nend\n"
    assert mod.read_text(encoding="utf-8") == "keep\nguard\nend\n"
