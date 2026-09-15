from pathlib import Path
import subprocess
import tempfile


def apply_unified_diff(workspace: Path, diff: str) -> None:
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".patch",
        delete=False,
    ) as handle:
        handle.write(diff)
        patch_path = Path(handle.name)

    try:
        preflight = subprocess.run(
            ["git", "apply", "--check", str(patch_path)],
            cwd=workspace,
            capture_output=True,
            text=True,
            check=False,
        )
        if preflight.returncode != 0:
            raise ValueError(f"patch does not apply cleanly: {preflight.stderr.strip()}")

        applied = subprocess.run(
            ["git", "apply", str(patch_path)],
            cwd=workspace,
            capture_output=True,
            text=True,
            check=False,
        )
        if applied.returncode != 0:
            raise RuntimeError(f"git apply failed: {applied.stderr.strip()}")
    finally:
        patch_path.unlink(missing_ok=True)
