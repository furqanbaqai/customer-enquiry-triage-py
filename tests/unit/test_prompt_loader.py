from pathlib import Path

import pytest

from src.utilities import PromptLoader, PromptLoaderError


def write_prompt(tmp_path: Path, content: str) -> Path:
    """Write a test Markdown prompt and return its path."""
    path = tmp_path / "prompt.md"
    path.write_text(content, encoding="utf-8")
    return path


def test_loads_valid_markdown_prompt(tmp_path: Path) -> None:
    path = write_prompt(tmp_path, "A prompt without variables.")

    assert PromptLoader().load_prompt(path, {}) == "A prompt without variables."


def test_replaces_one_placeholder_and_repeated_occurrences(tmp_path: Path) -> None:
    path = write_prompt(tmp_path, "{{MESSAGE}} / {{MESSAGE}}")

    assert PromptLoader().load_prompt(path, {"MESSAGE": "Help"}) == "Help / Help"


def test_replaces_multiple_placeholders(tmp_path: Path) -> None:
    path = write_prompt(tmp_path, "{{FIRST_NAME}}: {{MESSAGE}}")

    rendered = PromptLoader().load_prompt(path, {"FIRST_NAME": "Ada", "MESSAGE": "Help"})

    assert rendered == "Ada: Help"


def test_converts_supported_non_string_values(tmp_path: Path) -> None:
    path = write_prompt(tmp_path, "{{COUNT}} {{ACTIVE}} {{OPTIONAL}}")

    rendered = PromptLoader().load_prompt(path, {"COUNT": 3, "ACTIVE": True, "OPTIONAL": None})

    assert rendered == "3 True "


def test_allows_extra_variables_without_mutating_mapping(tmp_path: Path) -> None:
    path = write_prompt(tmp_path, "{{MESSAGE}}")
    variables: dict[str, object] = {"MESSAGE": "Help", "EXTRA": 7}
    original = variables.copy()

    assert PromptLoader().load_prompt(path, variables) == "Help"
    assert variables == original


def test_reports_all_unresolved_placeholders(tmp_path: Path) -> None:
    path = write_prompt(tmp_path, "{{MESSAGE}} {{CUSTOMER_NAME}} {{MESSAGE}}")

    with pytest.raises(
        PromptLoaderError, match="Unresolved prompt variables: CUSTOMER_NAME, MESSAGE"
    ):
        PromptLoader().load_prompt(path, {})


def test_rejects_missing_prompt_file(tmp_path: Path) -> None:
    with pytest.raises(PromptLoaderError, match="Prompt file does not exist"):
        PromptLoader().load_prompt(tmp_path / "missing.md", {})


def test_rejects_directory_prompt_path(tmp_path: Path) -> None:
    directory = tmp_path / "directory.md"
    directory.mkdir()

    with pytest.raises(PromptLoaderError, match="Prompt path is not a file"):
        PromptLoader().load_prompt(directory, {})


def test_rejects_empty_prompt_file(tmp_path: Path) -> None:
    path = write_prompt(tmp_path, " \n")

    with pytest.raises(PromptLoaderError, match="Prompt file is empty"):
        PromptLoader().load_prompt(path, {})


def test_reads_utf8_content(tmp_path: Path) -> None:
    path = write_prompt(tmp_path, "مرحباً {{NAME}}")

    assert PromptLoader().load_prompt(path, {"NAME": "عميل"}) == "مرحباً عميل"


@pytest.mark.parametrize("configured_value", [None, "", "   "])
def test_rejects_missing_or_blank_configuration(configured_value: object) -> None:
    loader = PromptLoader(lambda _key: configured_value)

    with pytest.raises(PromptLoaderError, match="configuration variable"):
        loader.load_configured_prompt("OFTL_AI_PROMPT_1", {})


def test_caches_only_template_not_rendered_prompt(tmp_path: Path) -> None:
    path = write_prompt(tmp_path, "Message: {{MESSAGE}}")
    loader = PromptLoader(lambda key: str(path) if key == "OFTL_AI_PROMPT_1" else None)

    first = loader.load_configured_prompt("OFTL_AI_PROMPT_1", {"MESSAGE": "Message A"})
    second = loader.load_configured_prompt("OFTL_AI_PROMPT_1", {"MESSAGE": "Message B"})

    assert first == "Message: Message A"
    assert second == "Message: Message B"
    assert "Message A" not in second
