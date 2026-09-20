"""Customer enquiry triage application source package."""

__all__ = ["main"]


def main(mode: str | None = None) -> None:
    """Load the application only when invoked, keeping workflow imports isolated."""
    from src.app import main as app_main

    app_main(mode)
