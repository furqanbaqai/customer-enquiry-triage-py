# -*- coding: utf-8 -*-

"""\
Copyright 2026-2028 openfintechlab.com, Inc. All rights reserved.\
Licenses: LICENSE.md\
Description: Provides centralized, configurable logging for the customer enquiry triage service.\
Reference: https://github.com/furqanbaqai/customer-enquiry-triage-py/blob/main/src/utilities/logging.py\
"""

# ruff: noqa: UP009 -- The project copyright header requires an encoding declaration.

import logging
from typing import Any, ClassVar

from src.config import ConfigLoader


class Logging:
    """Utility class for centralized application logging."""

    _DEFAULT_LEVEL = "INFO"
    _DEFAULT_FORMAT = "[%(asctime)s] %(levelname)s [%(name)s.%(funcName)s:%(lineno)d] %(message)s"
    _logger: ClassVar[logging.Logger] = logging.getLogger("OFTL")
    _configured: ClassVar[bool] = False

    @classmethod
    def configure(cls) -> None:
        """Configure the standard logging framework from application settings once."""
        if cls._configured:
            return

        level_name = str(ConfigLoader.get("OFTL_LOG_LEVEL", cls._DEFAULT_LEVEL)).upper()
        log_format = str(ConfigLoader.get("OFTL_LOG_FORMAT", cls._DEFAULT_FORMAT))
        log_level = getattr(logging, level_name, logging.INFO)

        logging.basicConfig(level=log_level, format=log_format)
        cls._logger.setLevel(log_level)
        cls._configured = True

    @classmethod
    def debug(cls, message: str, *args: Any, **kwargs: Any) -> None:
        """Write a debug log message."""
        cls.configure()
        cls._logger.debug(message, *args, **kwargs)

    @classmethod
    def info(cls, message: str, *args: Any, **kwargs: Any) -> None:
        """Write an informational log message."""
        cls.configure()
        cls._logger.info(message, *args, **kwargs)

    @classmethod
    def warning(cls, message: str, *args: Any, **kwargs: Any) -> None:
        """Write a warning log message."""
        cls.configure()
        cls._logger.warning(message, *args, **kwargs)

    @classmethod
    def error(cls, message: str, *args: Any, **kwargs: Any) -> None:
        """Write an error log message."""
        cls.configure()
        cls._logger.error(message, *args, **kwargs)
