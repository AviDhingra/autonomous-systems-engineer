from pathlib import Path

from anthropic import Anthropic
from anthropic.types import MessageParam, ToolParam, ToolResultBlockParam

from ase.tools import read_file, search_code

MODEL = "claude-sonnet-5"
MAX_TOKENS = 4096


TOOLS: list[ToolParam] = [
    {
        "name": "read_file",
        "description": (
            "Read one UTF-8 text file inside target/fleetops. "
            "Pass a repository-relative path such as "
            "target/fleetops/app/services/telemetry.py."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "relative_path": {
                    "type": "string",
                    "description": "Repository-relative FleetOps file path.",
                }
            },
            "required": ["relative_path"],
        },
    },
    {
        "name": "search_code",
        "description": (
            "Search Python files inside target/fleetops for a literal, "
            "case-sensitive text query."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Literal source text to search for.",
                }
            },
            "required": ["query"],
        },
    },
]


SYSTEM_PROMPT = """You are investigating a bug in the FleetOps Python backend.
Use the provided read-only tools to inspect repository evidence before concluding.
You may inspect FleetOps application code and tests, but do not ask to modify files.
Do not suggest changing tests merely to make a failure pass.
For this stage, do not output replacement source code or a patch.
When you have enough evidence, return an engineering diagnosis that names the
relevant application file and function, explains the root cause, and states the
intended behavior.
"""


def _get_string_argument(tool_input: dict[str, object], name: str) -> str:
    value = tool_input.get(name)

    if not isinstance(value, str):
        raise ValueError(f"tool argument {name!r} must be a string")

    return value


def _run_tool(
    repo_root: Path,
    tool_name: str,
    tool_input: dict[str, object],
) -> str:
    if tool_name == "read_file":
        relative_path = _get_string_argument(tool_input, "relative_path")
        return read_file(repo_root, relative_path)

    if tool_name == "search_code":
        query = _get_string_argument(tool_input, "query")
        matches = search_code(repo_root, query)

        if not matches:
            return "No matches found."

        return "\n".join(matches)

    raise ValueError(f"unknown tool: {tool_name}")



def investigate_ticket(repo_root: Path, ticket: str) -> str:
    client = Anthropic()

    messages: list[MessageParam] = [
        {
            "role": "user",
            "content": ticket,
        }
    ]

    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=messages,
            tools=TOOLS,
            tool_choice={
                "type": "auto",
                "disable_parallel_tool_use": True,
            },
        )

        if response.stop_reason == "tool_use":
            tool_use = next(
                block
                for block in response.content
                if block.type == "tool_use"
            )

            print(f"Claude requested {tool_use.name}: {tool_use.input}")

            try:
                result = _run_tool(
                    repo_root,
                    tool_use.name,
                    tool_use.input,
                )
                tool_result: ToolResultBlockParam = {
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": result,
                }
            except (OSError, ValueError) as exc:
                tool_result = {
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": str(exc),
                    "is_error": True,
                }

            messages.append(
                {
                    "role": "assistant",
                    "content": response.content,
                }
            )
            messages.append(
                {
                    "role": "user",
                    "content": [tool_result],
                }
            )
            continue

        if response.stop_reason != "end_turn":
            raise RuntimeError(
                f"Claude stopped before completing the investigation: "
                f"{response.stop_reason}"
            )

        text = "\n".join(
            block.text
            for block in response.content
            if block.type == "text"
        ).strip()

        if not text:
            raise RuntimeError("Claude completed the turn without diagnosis text")

        return text
