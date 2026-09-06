"""Unit tests for language detection and ISO 639-3 conversion."""

from typing import cast

import pytest

from src.utilities import LanguageValidator


@pytest.mark.parametrize(
    ("message", "expected_code"),
    [
        ("Please help me replace my lost debit card.", "eng"),
        ("أرجو مساعدتي في استبدال بطاقة الخصم المفقودة.", "ara"),
    ],
)
def test_detect_language_returns_iso_639_3(message: str, expected_code: str) -> None:
    assert LanguageValidator.detect_language(message) == expected_code


@pytest.mark.parametrize("message", ["", "   "])
def test_detect_language_rejects_blank_message(message: str) -> None:
    with pytest.raises(ValueError, match="must not be blank"):
        LanguageValidator.detect_language(message)


def test_detect_language_rejects_non_string() -> None:
    with pytest.raises(TypeError, match="must be a string"):
        LanguageValidator.detect_language(cast(str, 123))
