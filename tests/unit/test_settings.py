from pathlib import Path

from customer_enquiry_triage.config import ConfigLoader


def test_get_returns_configuration_by_key(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "GENAI_URL=https://example.com/v1/chat/completions\n"
        "api_lowercase=ignored\n",
        encoding="utf-8",
    )

    ConfigLoader.load_configurations(env_file)

    assert ConfigLoader.get("GENAI_URL") == "https://example.com/v1/chat/completions"
    assert ConfigLoader.get("MISSING_KEY", "fallback") == "fallback"
    assert ConfigLoader.get("api_lowercase") is None
