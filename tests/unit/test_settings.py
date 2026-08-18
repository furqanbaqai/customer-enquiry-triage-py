from pathlib import Path

from customer_enquiry_triage.config import ConfigLoader


def test_loads_genai_url_from_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("GENAI_URL=https://example.com/v1/chat/completions\n", encoding="utf-8")

    settings = ConfigLoader.load(env_file)

    assert settings.genai_url == "https://example.com/v1/chat/completions"
