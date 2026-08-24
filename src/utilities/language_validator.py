"""
Copyright 2026-2028 openfintechlab.com, Inc. All rights reserved.
Licenses: LICENSE.md
Description: Detects the language of customer messages using ISO 639-3 codes.
Reference: https://github.com/furqanbaqai/customer-enquiry-triage-py
"""

from lingua import LanguageDetectorBuilder


class LanguageValidator:
    """Detect the language used by a plain-text message."""

    _detector = LanguageDetectorBuilder.from_all_languages().build()

    @classmethod
    def detect_language(cls, message: str) -> str:
        """Return the detected language as a lowercase ISO 639-3 code."""
        if not isinstance(message, str):
            raise TypeError("[ERR-15] The message must be a string")
        if not message.strip():
            raise ValueError("[ERR-16] The message must not be blank")

        language = cls._detector.detect_language_of(message)
        if language is None:
            raise ValueError("[ERR-17] The message language could not be detected")
        return language.iso_code_639_3.name.lower()
