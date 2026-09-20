from pathlib import Path

from ase.models import FixProposal

FLEETOPS_APP_ROOT = Path("target/fleetops/app")

def _resolve_write_path(repo_root: Path, relative_path: str) -> Path:
    repo_root = repo_root.resolve()
    allowed_root = (repo_root / FLEETOPS_APP_ROOT).resolve()
    candidate = (repo_root / relative_path).resolve()

    try:
        candidate.relative_to(allowed_root)
    except ValueError as exc:
        raise ValueError(
            f"path must stay inside {FLEETOPS_APP_ROOT.as_posix()}: {relative_path}"
        ) from exc

    if not candidate.is_file():
        raise ValueError(f"target file does not exist: {relative_path}")

    return candidate


def apply_fix(repo_root: Path, proposal: FixProposal) -> str:
    path = _resolve_write_path(repo_root, proposal.file_path)
    old_content = path.read_text(encoding="utf-8")
    path.write_text(proposal.new_content, encoding="utf-8")
    return old_content
