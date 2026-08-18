"""Application entry point and composition root."""

from customer_enquiry_triage.config import ConfigLoader


def main() -> None:
    """Start the customer enquiry triage service."""
    settings = ConfigLoader.load()
    print("Customer enquiry triage service is ready.")
    print("Service URL:", settings.genai_url)
