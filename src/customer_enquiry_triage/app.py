"""Application entry point and composition root."""

from customer_enquiry_triage.config import ConfigLoader
from customer_enquiry_triage.utilities import Logging


def main() -> None:
    """Start the customer enquiry triage service."""
    ConfigLoader.load_configurations()
    genai_url = ConfigLoader.get("GENAI_URL")
    displayBanner()

def displayBanner() -> None:
    """Display the application banner."""
    banner = "GEN-AI-Proxy"
    Logging.info(banner)