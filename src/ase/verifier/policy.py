from dataclasses import dataclass
from pathlib import PurePosixPath

from .models import GateResult


@dataclass(frozen=True, slots=True)
class PatchPolicy:
    allowed_prefixes: tuple[str, ...] = ("target/fleetops/app/",)
    forbidden_prefixes: tuple[str, ...] = (
        ".github/",
        "scenarios/",
        "evals/",
        "tests/",
        "target/fleetops/tests/",
    )
    allowed_suffixes: tuple[str, ...] = (".py",)
    max_changed_files: int = 4
    max_changed_lines: int = 120


@dataclass(frozen=True, slots=True)
class PatchFacts:
    paths: tuple[str, ...]
    changed_lines: int


def paths_from_diff(diff: str) -> tuple[str, ...]:
    paths: set[str] = set()
    for line in diff.splitlines():
        if not line.startswith(("--- ", "+++ ")):
            continue
        raw = line[4:].strip().split("\t", maxsplit=1)[0]
        if raw == "/dev/null":
            continue
        if raw.startswith(("a/", "b/")):
            raw = raw[2:]
        paths.add(raw)
    return tuple(sorted(paths))


def changed_line_count(diff: str) -> int:
    count = 0
    for line in diff.splitlines():
        if line.startswith(("+++ ", "--- ")):
            continue
        if line.startswith(("+", "-")):
            count += 1
    return count


def inspect_patch(diff: str) -> PatchFacts:
    return PatchFacts(paths=paths_from_diff(diff), changed_lines=changed_line_count(diff))


def check_patch_policy(diff: str, policy: PatchPolicy) -> GateResult:
    facts = inspect_patch(diff)
    problems: list[str] = []

    if not facts.paths:
        problems.append("patch does not change any file")
    if len(facts.paths) > policy.max_changed_files:
        problems.append(
            f"too many changed files: {len(facts.paths)} > {policy.max_changed_files}"
        )
    if facts.changed_lines > policy.max_changed_lines:
        problems.append(
            f"too many changed lines: {facts.changed_lines} > {policy.max_changed_lines}"
        )

    for raw_path in facts.paths:
        normalized = PurePosixPath(raw_path)
        if normalized.is_absolute() or ".." in normalized.parts:
            problems.append(f"unsafe path: {raw_path}")
            continue
        if any(raw_path.startswith(prefix) for prefix in policy.forbidden_prefixes):
            problems.append(f"forbidden path: {raw_path}")
        if not any(raw_path.startswith(prefix) for prefix in policy.allowed_prefixes):
            problems.append(f"path is outside allowed application code: {raw_path}")
        if not raw_path.endswith(policy.allowed_suffixes):
            problems.append(f"unsupported file type: {raw_path}")

    return GateResult(
        name="patch_policy",
        passed=not problems,
        details="ok" if not problems else "; ".join(problems),
    )
