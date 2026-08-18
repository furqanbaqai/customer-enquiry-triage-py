"""Typed application configuration loaded from environment variables."""

from dataclasses import dataclass
from pathlib import Path

from environs import Env


@dataclass(frozen=True, slots=True)
class Settings:
    """Configuration required by the application."""

    genai_url: str


class ConfigLoader:
    """Load and validate application configuration from the environment."""

    _project_root = Path(__file__).resolve().parents[3]

    @classmethod
    def load(cls, env_file: Path | None = None) -> Settings:
        """Load settings, using the project-level ``.env`` file by default."""
        env = Env(eager=False)
        env.read_env(env_file or cls._project_root / ".env")

        settings = Settings(genai_url=env.str("GENAI_URL"))
        env.seal()
        return settings
