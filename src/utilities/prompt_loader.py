"""Load and render configured Markdown prompt templates."""

import re
from collections.abc import Callable, Mapping
from pathlib import Path
from threading import RLock

from src.config import ConfigLoader
from src.utilities.logging import Logging


class PromptLoaderError(ValueError):
    """Raised when a prompt template cannot be loaded or rendered safely."""


class PromptLoader:
    """Load UTF-8 Markdown templates and replace ``{{VARIABLE_NAME}}`` placeholders."""

    _PLACEHOLDER_PATTERN = re.compile(r"{{([A-Z][A-Z0-9_]*)}}")

    def __init__(self, configuration_getter: Callable[[str], object] = ConfigLoader.get) -> None:
        """Create a loader using an injectable configuration lookup function."""
        self._configuration_getter = configuration_getter
        self._templates: dict[Path, str] = {}
        self._cache_lock = RLock()

    def load_configured_prompt(
        self, configuration_key: str, variables: Mapping[str, object]
    ) -> str:
        """Resolve ``configuration_key`` and render its referenced prompt template."""
        configured_path = self._configuration_getter(configuration_key)
        if configured_path is None:
            raise PromptLoaderError(
                f"[ERR-27] Prompt configuration variable is missing: {configuration_key}"
            )
        if not isinstance(configured_path, str) or not configured_path.strip():
            raise PromptLoaderError(
                f"[ERR-28] Prompt configuration variable is blank: {configuration_key}"
            )

        Logging.debug(
            "Loading prompt template configured by %s from %s", configuration_key, configured_path
        )
        return self.load_prompt(Path(configured_path), variables)

    def load_prompt(self, prompt_path: Path | str, variables: Mapping[str, object]) -> str:
        """Load a Markdown template and render it with a flat variable mapping.

        ``None`` values are rendered as empty strings. The supplied mapping is never modified.
        """
        path = Path(prompt_path)
        template = self._load_template(path)
        supplied_names = set(variables)

        def replace(match: re.Match[str]) -> str:
            variable_name = match.group(1)
            if variable_name not in variables:
                return match.group(0)
            value = variables[variable_name]
            return "" if value is None else str(value)

        rendered = self._PLACEHOLDER_PATTERN.sub(replace, template)
        unresolved = sorted(set(self._PLACEHOLDER_PATTERN.findall(rendered)))
        if unresolved:
            raise PromptLoaderError(
                f"[ERR-29] Unresolved prompt variables: {', '.join(unresolved)}"
            )

        unused = sorted(supplied_names - set(self._PLACEHOLDER_PATTERN.findall(template)))
        if unused:
            Logging.debug("Unused prompt variables supplied: %s", ", ".join(unused))
        return rendered

    def _load_template(self, prompt_path: Path) -> str:
        """Validate and cache the original prompt template."""
        if prompt_path.suffix.lower() != ".md":
            raise PromptLoaderError(
                f"[ERR-30] Prompt file must be a Markdown (.md) file: {prompt_path}"
            )
        if not prompt_path.exists():
            raise PromptLoaderError(f"[ERR-31] Prompt file does not exist: {prompt_path}")
        if not prompt_path.is_file():
            raise PromptLoaderError(f"[ERR-32] Prompt path is not a file: {prompt_path}")

        resolved_path = prompt_path.resolve()
        with self._cache_lock:
            cached = self._templates.get(resolved_path)
            if cached is not None:
                return cached
            try:
                template = resolved_path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as error:
                raise PromptLoaderError(
                    f"[ERR-33] Unable to read prompt file: {resolved_path}"
                ) from error
            if not template.strip():
                raise PromptLoaderError(f"[ERR-34] Prompt file is empty: {resolved_path}")
            self._templates[resolved_path] = template
            return template
