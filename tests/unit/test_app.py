import pytest

from customer_enquiry_triage.app import main


def test_main_reports_ready(capsys: pytest.CaptureFixture[str]) -> None:
    main()

    captured = capsys.readouterr()
    assert "Customer enquiry triage service is ready.\n" in captured.out
    assert "Service URL: http://dev.qwen2.5.openfintechlab.com:8080" in captured.out
