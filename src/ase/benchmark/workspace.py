from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
import shutil
import subprocess
import tempfile


def _copy_path(source: Path, destination: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, destination, dirs_exist_ok=True)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def prepare_workspace(project_root: Path) -> Path:
    workspace = Path(tempfile.mkdtemp(prefix="ase-workspace-"))
    for relative in ("target", "pyproject.toml", ".gitignore"):
        source = project_root / relative
        if source.exists():
            _copy_path(source, workspace / relative)

    subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
    subprocess.run(["git", "add", "."], cwd=workspace, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=ASE Benchmark",
            "-c",
            "user.email=benchmark@example.invalid",
            "commit",
            "-q",
            "-m",
            "baseline",
        ],
        cwd=workspace,
        check=True,
    )
    return workspace


@contextmanager
def isolated_workspace(project_root: Path) -> Iterator[Path]:
    workspace = prepare_workspace(project_root)
    try:
        yield workspace
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
