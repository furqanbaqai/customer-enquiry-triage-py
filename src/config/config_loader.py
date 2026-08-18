"""Generic application configuration loader."""

import os
import re
from pathlib import Path
from typing import Any, ClassVar

from dotenv import dotenv_values


class ConfigLoader:
    """Load configuration from the project ``.env`` file and process environment."""

    _KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")
    _ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
    configurations: ClassVar[dict[str, str]] = {}

    @classmethod
    def decrypt(cls, value: str) -> str:
        """Decrypt a secret value when a real decryption implementation is available."""
        return value

    @classmethod
    def _is_valid_key(cls, key: str) -> bool:
        """Return whether a key follows the supported environment-variable format."""
        return bool(cls._KEY_PATTERN.fullmatch(key))

    @classmethod
    def load_configurations(cls, env_file: Path | None = None) -> dict[str, str]:
        """Load valid variables, with process environment taking precedence over ``.env``."""
        file_values = {
            key: value
            for key, value in dotenv_values(env_file or cls._ENV_FILE).items()
            if value is not None
        }
        merged_values = file_values | dict(os.environ)

        cls.configurations = {
            key: cls.decrypt(value) if key.endswith("_SECRET") else value
            for key, value in merged_values.items()
            if cls._is_valid_key(key)
        }
        return cls.configurations.copy()

    @classmethod
    def get(cls, key: str, default: Any = None) -> Any:
        """Return a configuration value by key, or ``default`` when it is absent."""
        if not cls.configurations:
            cls.load_configurations()
        return cls.configurations.get(key, default)
