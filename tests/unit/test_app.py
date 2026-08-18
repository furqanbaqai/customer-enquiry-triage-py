import logging

import pytest

from customer_enquiry_triage.app import main


def test_main_reports_ready(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="OFTL")
    main()

    assert "Customer enquiry triage service is ready." in caplog.messages
    assert any(
        message.startswith("Service URL: http://dev.qwen2.5.openfintechlab.com:8080")
        for message in caplog.messages
    )
