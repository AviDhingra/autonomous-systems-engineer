import subprocess
from pathlib import Path

from ase.agent import propose_fix
from ase.apply_fix import apply_fix
from ase.verify import VerificationResult, verify_repository

TICKET_PATH = Path("scenarios/S01-duplicate-telemetry/ticket.md")


def _git_diff(repo_root: Path, relative_path: str) -> str:
    completed = subprocess.run(
        ["git", "diff", "--", relative_path],
        cwd=repo_root.resolve(),
        capture_output=True,
        text=True,
        check=False,
    )

    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or "git diff failed")

    return completed.stdout


def _print_verification(result: VerificationResult) -> None:
    for check in result.checks:
        status = "PASS" if check.passed else "FAIL"
        print(f"{status}: {check.name}")

        if not check.passed:
            if check.stdout.strip():
                print(check.stdout.rstrip())
            if check.stderr.strip():
                print(check.stderr.rstrip())


def main() -> int:
    repo_root = Path.cwd()
    ticket_path = repo_root / TICKET_PATH
    ticket = ticket_path.read_text(encoding="utf-8")

    print("1. Investigating ticket with Claude")
    proposal = propose_fix(repo_root, ticket)

    print("\n2. Proposed repair")
    print(f"File: {proposal.file_path}")
    print(proposal.explanation)

    print("\n3. Applying validated file replacement")
    apply_fix(repo_root, proposal)

    print("\n4. Git diff against committed baseline")
    diff = _git_diff(repo_root, proposal.file_path)
    if diff.strip():
        print(diff.rstrip())
    else:
        print("(no diff: repaired file matches the committed baseline)")

    print("\n5. Running independent verification")
    verification = verify_repository(repo_root)
    _print_verification(verification)

    print()
    if verification.passed:
        print("VERIFIED")
        return 0

    print("FAILED")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
