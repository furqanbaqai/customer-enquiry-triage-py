"""Application entry point and composition root."""

from src.config import ConfigLoader
from src.utilities import Logging


def main() -> None:
    """Start the customer enquiry triage service."""
    ConfigLoader.load_configurations()
    genai_url = ConfigLoader.get("GENAI_URL")
    display_banner()
    Logging.info("Customer enquiry triage service is ready.")
    Logging.info("Service URL: %s", genai_url)


def display_banner() -> None:
    """Display the application banner."""
    banner = "GEN-AI-Proxy"
    Logging.info(banner)
