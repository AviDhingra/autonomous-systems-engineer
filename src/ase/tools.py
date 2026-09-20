from pathlib import Path

FLEETOPS_ROOT = Path("target/fleetops")

def _resolve_fleetops_path(repo_root: Path, relative_path: str) -> Path:
    repo_root = repo_root.resolve()
    allowed_root = (repo_root / FLEETOPS_ROOT).resolve()
    candidate = (repo_root / relative_path).resolve()

    try:
        candidate.relative_to(allowed_root)
    except ValueError as exc:
        raise ValueError(
            f"path must stay inside {FLEETOPS_ROOT.as_posix()}: {relative_path}"
        ) from exc

    return candidate

def read_file(repo_root: Path, relative_path: str) -> str:
    path = _resolve_fleetops_path(repo_root, relative_path)
    if not path.is_file():
        raise ValueError(f"not a file: {relative_path}")
    return path.read_text(encoding="utf-8")



def search_code(repo_root: Path, query: str) -> list[str]:
    repo_root = repo_root.resolve()
    fleetops_root = (repo_root / FLEETOPS_ROOT).resolve()
    matches: list[str] = []

    if not query.strip():
        raise ValueError("query must not be empty")


    for path in sorted(fleetops_root.rglob("*.py")):
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            if query in line:
                relative_path = path.relative_to(repo_root).as_posix()
                matches.append(f"{relative_path}:{line_number}: {line.strip()}")

    return matches

