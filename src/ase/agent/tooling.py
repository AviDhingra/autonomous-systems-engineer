from dataclasses import asdict, dataclass
import json

from langchain_core.tools import BaseTool, tool

from ase.tools.models import FileSlice, SearchMatch
from ase.tools.repository import RepositoryTools

from .models import ToolEvent


@dataclass
class ModelToolBundle:
    tools: list[BaseTool]
    searches: list[SearchMatch]
    files: list[FileSlice]
    events: list[ToolEvent]

    @property
    def by_name(self) -> dict[str, BaseTool]:
        return {
            item.name: item
            for item in self.tools
        }


def build_repository_model_tools(
    repository: RepositoryTools,
) -> ModelToolBundle:
    searches: list[SearchMatch] = []
    files: list[FileSlice] = []
    events: list[ToolEvent] = []

    @tool
    def list_tree(
        max_depth: int = 4,
        limit: int = 300,
    ) -> str:
        """List repository paths inside the isolated workspace."""
        try:
            result = repository.list_tree(
                max_depth=max_depth,
                limit=limit,
            )
        except Exception as exc:
            message = (
                f"{type(exc).__name__}: {exc}"
            )
            events.append(
                ToolEvent(
                    name="list_tree",
                    arguments={
                        "max_depth": max_depth,
                        "limit": limit,
                    },
                    success=False,
                    output_preview=message[:500],
                )
            )
            return f"ERROR: {message}"

        output = json.dumps(result)
        events.append(
            ToolEvent(
                name="list_tree",
                arguments={
                    "max_depth": max_depth,
                    "limit": limit,
                },
                success=True,
                output_preview=output[:500],
            )
        )
        return output

    @tool
    def search_text(
        query: str,
        limit: int = 30,
    ) -> str:
        """Search Python source for literal text."""
        try:
            result = repository.search_text(
                query,
                limit=limit,
            )
        except Exception as exc:
            message = (
                f"{type(exc).__name__}: {exc}"
            )
            events.append(
                ToolEvent(
                    name="search_text",
                    arguments={
                        "query": query,
                        "limit": limit,
                    },
                    success=False,
                    output_preview=message[:500],
                )
            )
            return f"ERROR: {message}"

        searches.extend(result)
        output = json.dumps(
            [
                asdict(item)
                for item in result
            ]
        )
        events.append(
            ToolEvent(
                name="search_text",
                arguments={
                    "query": query,
                    "limit": limit,
                },
                success=True,
                output_preview=output[:500],
            )
        )
        return output

    @tool
    def read_file(
        relative_path: str,
        start_line: int = 1,
        end_line: int = 200,
    ) -> str:
        """Read a bounded line range from one file inside the workspace."""
        try:
            result = repository.read_file(
                relative_path,
                start_line=start_line,
                end_line=end_line,
            )
        except Exception as exc:
            message = (
                f"{type(exc).__name__}: {exc}"
            )
            events.append(
                ToolEvent(
                    name="read_file",
                    arguments={
                        "relative_path": relative_path,
                        "start_line": start_line,
                        "end_line": end_line,
                    },
                    success=False,
                    output_preview=message[:500],
                )
            )
            return f"ERROR: {message}"

        files.append(result)
        output = json.dumps(asdict(result))
        events.append(
            ToolEvent(
                name="read_file",
                arguments={
                    "relative_path": relative_path,
                    "start_line": start_line,
                    "end_line": end_line,
                },
                success=True,
                output_preview=output[:500],
            )
        )
        return output

    return ModelToolBundle(
        tools=[
            list_tree,
            search_text,
            read_file,
        ],
        searches=searches,
        files=files,
        events=events,
    )
