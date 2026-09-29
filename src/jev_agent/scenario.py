"""Inject a scenario's bug for the duration of a demo run.

The committed FleetOps baseline is the *fixed* code; a scenario's
`bug.patch` reintroduces its fault. Without applying it first, the agent has
nothing to find. `injected_bug` applies the patch, and on exit restores the
target tree to the committed baseline, including any file a governed run
applied along the way, so every demo starts and ends from the same state.
"""

import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

TARGET_DIR = "target/fleetops"


def _git(repo_root: Path, *args: str, stdin: bytes | None = None) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        input=stdin,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {stderr}")
    return completed.stdout.decode("utf-8", errors="replace")


@contextmanager
def injected_bug(repo_root: Path, scenario: str) -> Iterator[None]:
    """Apply `scenarios/<scenario>/bug.patch`, then restore the target tree.

    Refuses to start if `target/fleetops` already has uncommitted changes,
    because restoring would discard them.
    """
    patch = repo_root / "scenarios" / scenario / "bug.patch"
    if _git(repo_root, "status", "--porcelain", "--", TARGET_DIR).strip():
        raise RuntimeError(
            f"{TARGET_DIR} has uncommitted changes; commit or revert them before running a demo"
        )
    # A checkout with `core.autocrlf=true` rewrites the patch file to CRLF,
    # which `git apply` rejects as corrupt. Normalize to LF and feed it on stdin.
    patch_bytes = patch.read_bytes().replace(b"\r\n", b"\n")
    _git(repo_root, "apply", "-", stdin=patch_bytes)
    try:
        yield
    finally:
        _git(repo_root, "checkout", "--", TARGET_DIR)
