from ase.agent.tooling import build_repository_model_tools
from ase.tools.models import FileSlice, SearchMatch
from ase.tools.repository import RepositoryTools


def test_bundle_exposes_only_bounded_read_tools(tmp_path) -> None:
    repository = RepositoryTools(tmp_path)

    bundle = build_repository_model_tools(repository)

    assert set(bundle.by_name) == {
        "list_tree",
        "search_text",
        "read_file",
    }
    assert bundle.searches == []
    assert bundle.files == []
    assert bundle.events == []


def test_read_file_records_file_slice_and_success_event(tmp_path) -> None:
    source = tmp_path / "example.py"
    source.write_text(
        "def greet() -> str:\n"
        '    return "hello"\n',
        encoding="utf-8",
    )

    repository = RepositoryTools(tmp_path)
    bundle = build_repository_model_tools(repository)

    output = bundle.by_name["read_file"].invoke(
        {
            "relative_path": "example.py",
            "start_line": 1,
            "end_line": 2,
        }
    )

    assert "greet" in output

    assert len(bundle.files) == 1
    assert isinstance(bundle.files[0], FileSlice)
    assert bundle.files[0].path == "example.py"
    assert "greet" in bundle.files[0].content

    assert len(bundle.events) == 1
    event = bundle.events[0]
    assert event.name == "read_file"
    assert event.success is True
    assert event.arguments == {
        "relative_path": "example.py",
        "start_line": 1,
        "end_line": 2,
    }


def test_search_text_records_matches_and_success_event(tmp_path) -> None:
    source = tmp_path / "service.py"
    source.write_text(
        "def calculate_total(value: int) -> int:\n"
        "    return value * 2\n",
        encoding="utf-8",
    )

    repository = RepositoryTools(tmp_path)
    bundle = build_repository_model_tools(repository)

    output = bundle.by_name["search_text"].invoke(
        {
            "query": "calculate_total",
            "limit": 10,
        }
    )

    assert "calculate_total" in output

    assert bundle.searches
    assert all(
        isinstance(match, SearchMatch)
        for match in bundle.searches
    )

    assert len(bundle.events) == 1
    event = bundle.events[0]
    assert event.name == "search_text"
    assert event.success is True
    assert event.arguments == {
        "query": "calculate_total",
        "limit": 10,
    }


def test_read_file_rejects_path_escape_as_controlled_error(
    tmp_path,
) -> None:
    outside_file = tmp_path.parent / "outside.txt"
    outside_file.write_text(
        "this must not be readable through RepositoryTools",
        encoding="utf-8",
    )

    repository = RepositoryTools(tmp_path)
    bundle = build_repository_model_tools(repository)

    output = bundle.by_name["read_file"].invoke(
        {
            "relative_path": "../outside.txt",
            "start_line": 1,
            "end_line": 10,
        }
    )

    assert output.startswith("ERROR:")
    assert bundle.files == []

    assert len(bundle.events) == 1
    event = bundle.events[0]
    assert event.name == "read_file"
    assert event.success is False
    assert event.arguments == {
        "relative_path": "../outside.txt",
        "start_line": 1,
        "end_line": 10,
    }
    assert event.output_preview


def test_list_tree_records_success_event(tmp_path) -> None:
    (tmp_path / "package").mkdir()
    (tmp_path / "package" / "module.py").write_text(
        "VALUE = 1\n",
        encoding="utf-8",
    )

    repository = RepositoryTools(tmp_path)
    bundle = build_repository_model_tools(repository)

    output = bundle.by_name["list_tree"].invoke(
        {
            "max_depth": 4,
            "limit": 30,
        }
    )

    assert "module.py" in output

    assert len(bundle.events) == 1
    event = bundle.events[0]
    assert event.name == "list_tree"
    assert event.success is True
    assert event.arguments == {
        "max_depth": 4,
        "limit": 30,
    }