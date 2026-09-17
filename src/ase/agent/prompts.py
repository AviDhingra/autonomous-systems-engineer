from .models import Investigation
from ase.verifier.models import VerificationReport


INVESTIGATION_SYSTEM_PROMPT = """
You are a software engineer investigating one bug in an isolated
repository.

Rules:
- Use only the provided read-only tools.
- Gather evidence before making conclusions.
- Prefer focused searches and bounded file reads.
- Do not invent files or line numbers.
- Do not propose a patch yet.
- Stop when you have enough evidence to explain the likely fault.
""".strip()


DIAGNOSIS_SYSTEM_PROMPT = """
You are diagnosing a software defect using evidence already gathered
from the repository.

Return only the requested structured diagnosis.
Use evidence that exists in the supplied investigation.
Do not claim certainty that the evidence does not support.
""".strip()


PATCH_SYSTEM_PROMPT = """
You are proposing a small software repair.

Return only the requested structured result.
The diff must be a valid unified diff against the CURRENT workspace.
Change only application source needed for the defect.
Do not edit tests, evaluator files, scenario files, pyproject.toml,
or hidden-oracle material.
Keep the change minimal.
""".strip()


REPAIR_SYSTEM_PROMPT = """
A previous repair was applied but visible deterministic verification
failed.

Use the supplied verification failures and current source state.
Return one small incremental unified diff against the CURRENT workspace.
Do not edit tests or evaluator files.
Address the actual failed checks rather than hiding them.
""".strip()


def investigation_context(
    ticket: str,
    investigation: Investigation,
) -> str:
    file_blocks = []

    for item in investigation.files:
        file_blocks.append(
            "\n".join(
                [
                    f"FILE: {item.path}",
                    (
                        "LINES: "
                        f"{item.start_line}-{item.end_line}"
                    ),
                    item.content,
                ]
            )
        )

    return "\n\n".join(
        [
            "ENGINEERING TICKET:",
            ticket,
            "",
            "INVESTIGATION SUMMARY:",
            investigation.summary,
            "",
            "FILES READ:",
            "\n\n".join(file_blocks),
        ]
    )


def verification_context(
    report: VerificationReport,
) -> str:
    blocks = []

    for gate in report.gates:
        if gate.passed:
            continue

        blocks.append(
            "\n".join(
                [
                    f"GATE: {gate.name}",
                    "STATUS: FAILED",
                    gate.details,
                ]
            )
        )

    return "\n\n".join(blocks)
