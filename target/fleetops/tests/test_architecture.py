import ast
from pathlib import Path

SERVICE_ROOT = Path("target/fleetops/app/services")
ROUTE_FILES = [
    Path("target/fleetops/app/api/devices.py"),
    Path("target/fleetops/app/api/telemetry.py"),
]



def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
        elif isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)

    return imported


def test_service_layer_does_not_import_http_or_sqlalchemy() -> None:
    violations: list[str] = []

    for path in SERVICE_ROOT.glob("*.py"):
        for module in _imports(path):
            if module.startswith("fastapi") or module.startswith("sqlalchemy"):
                violations.append(f"{path}: imports {module}")

    assert not violations, "\n".join(violations)


def test_route_modules_do_not_import_repository_layer() -> None:
    violations: list[str] = []
    for path in ROUTE_FILES:
        for module in _imports(path):
            if "repositories" in module:
                violations.append(f"{path}: imports {module}")
    assert not violations, "\n".join(violations)
