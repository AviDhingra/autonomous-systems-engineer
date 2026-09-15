from pathlib import Path
import re

from .models import FileSlice, SearchMatch


class RepositoryTools:
    """Read-only, bounded access to one isolated workspace."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    @property
    def root(self) -> Path:
        return self._root

    def _safe_path(self, relative_path: str) -> Path:
        candidate = (self._root / relative_path).resolve()
        try:
            candidate.relative_to(self._root)
        except ValueError as exc:
            raise ValueError(f"path escapes workspace: {relative_path}") from exc
        return candidate

    def list_tree(self, *, max_depth: int = 4, limit: int = 500) -> list[str]:
        if max_depth < 1:
            raise ValueError("max_depth must be at least 1")
        if not 1 <= limit <= 2000:
            raise ValueError("limit must be between 1 and 2000")

        paths: list[str] = []
        for path in sorted(self._root.rglob("*")):
            relative = path.relative_to(self._root)
            if len(relative.parts) > max_depth:
                continue
            if any(part.startswith(".") for part in relative.parts):
                continue
            paths.append(relative.as_posix())
            if len(paths) >= limit:
                break
        return paths

    def read_file(
        self,
        relative_path: str,
        *,
        start_line: int = 1,
        end_line: int = 200,
    ) -> FileSlice:
        if start_line < 1:
            raise ValueError("start_line must be at least 1")
        if end_line < start_line:
            raise ValueError("end_line must be greater than or equal to start_line")
        if end_line - start_line + 1 > 400:
            raise ValueError("a single read may contain at most 400 lines")

        path = self._safe_path(relative_path)
        if not path.is_file():
            raise ValueError(f"not a readable file: {relative_path}")

        lines = path.read_text(encoding="utf-8").splitlines()
        selected = lines[start_line - 1 : end_line]
        actual_end = start_line + len(selected) - 1 if selected else start_line - 1
        return FileSlice(
            path=relative_path,
            start_line=start_line,
            end_line=actual_end,
            content="\n".join(selected),
        )

    def search_text(self, query: str, *, limit: int = 50) -> list[SearchMatch]:
        if not query.strip():
            raise ValueError("query must not be empty")
        if not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")

        pattern = re.compile(re.escape(query), re.IGNORECASE)
        matches: list[SearchMatch] = []

        for path in sorted(self._root.rglob("*.py")):
            relative = path.relative_to(self._root)
            if any(part.startswith(".") for part in relative.parts):
                continue
            for line_number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(),
                start=1,
            ):
                if pattern.search(line):
                    matches.append(
                        SearchMatch(
                            path=relative.as_posix(),
                            line=line_number,
                            text=line.strip(),
                        )
                    )
                    if len(matches) >= limit:
                        return matches
        return matches
