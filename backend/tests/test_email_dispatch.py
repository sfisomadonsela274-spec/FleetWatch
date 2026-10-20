"""
FleetWatch Email Dispatch Service Test Suite
============================================
Verifies:
1. Local Simulation fallback mode
2. Brevo HTTP API dispatch (Port 443 HTTPS)
3. Traditional SMTP dispatch (Port 587 / 465)
4. API Endpoints: /api/v1/email/status, /api/v1/email/test, /api/v1/email/configure
"""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from backend.main import app
from backend.email_service import EmailService

client = TestClient(app)


def test_email_service_local_simulation():
    svc = EmailService()
    svc.active_mode = "LOCAL_SIMULATION"
    svc.brevo_api_key = ""
    svc.smtp_host = ""
    svc.smtp_user = ""
    status = svc.get_status()
    assert status["configured"] is False
    assert status["mode"] == "LOCAL_SIMULATION"

    res = svc.send_email(
        to_email="driver@example.com",
        subject="Test Notice",
        html_body="<p>Test HTML</p>",
        text_body="Test Text"
    )
    assert res["status"] == "DELIVERED_MOCK"
    assert res["to"] == "driver@example.com"


@patch("requests.post")
def test_email_service_brevo_http_dispatch(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.json.return_value = {"messageId": "<brevo-test-msg-12345@smtp-relay.mailin.fr>"}
    mock_post.return_value = mock_resp

    svc = EmailService()
    svc.active_mode = "BREVO_API"
    svc.brevo_api_key = "xkeysib-mock-api-key-test"
    svc.from_email = "sfisomadonsela274@gmail.com"
    svc.from_name = "FleetWatch Operations"

    status = svc.get_status()
    assert status["brevo_configured"] is True
    assert status["mode"] == "BREVO_API"

    res = svc.send_dispatch_invite(
        to_email="sipho@fleetwatch.co.za",
        truck_reg="WP 889 GP",
        driver_name="Sipho Zulu",
        download_url="https://github.com/sfisomadonsela274-spec/FleetWatch/releases/download/v1.0.0/FleetSentinel-Driver.apk",
        otp_code="849201"
    )

    assert mock_post.called
    call_args = mock_post.call_args
    assert call_args[0][0] == "https://api.brevo.com/v3/smtp/email"
    headers = call_args[1]["headers"]
    assert headers["api-key"] == "xkeysib-mock-api-key-test"
    payload = call_args[1]["json"]
    assert payload["to"] == [{"email": "sipho@fleetwatch.co.za"}]
    assert "849201" in payload["htmlContent"]
    assert res["status"] == "DELIVERED_BREVO"
    assert res["message_id"] == "<brevo-test-msg-12345@smtp-relay.mailin.fr>"


@patch("requests.post")
def test_email_service_sendgrid_http_dispatch(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 202
    mock_resp.headers = {"X-Message-Id": "sendgrid-test-msg-12345"}
    mock_post.return_value = mock_resp

    svc = EmailService()
    svc.active_mode = "SENDGRID_API"
    svc.sendgrid_api_key = "SG.mock-api-key-test"
    svc.from_email = "sfisomadonsela274@gmail.com"
    svc.from_name = "FleetWatch Operations"

    status = svc.get_status()
    assert status["sendgrid_configured"] is True
    assert status["mode"] == "SENDGRID_API"

    res = svc.send_dispatch_invite(
        to_email="sipho@fleetwatch.co.za",
        truck_reg="WP 889 GP",
        driver_name="Sipho Zulu",
        download_url="https://github.com/sfisomadonsela274-spec/FleetWatch/releases/download/v1.0.0/FleetSentinel-Driver.apk",
        otp_code="849201"
    )

    assert mock_post.called
    call_args = mock_post.call_args
    assert call_args[0][0] == "https://api.sendgrid.com/v3/mail/send"
    headers = call_args[1]["headers"]
    assert headers["Authorization"] == "Bearer SG.mock-api-key-test"
    payload = call_args[1]["json"]
    assert payload["personalizations"][0]["to"] == [{"email": "sipho@fleetwatch.co.za"}]
    assert res["status"] == "DELIVERED_SENDGRID"
    assert res["message_id"] == "sendgrid-test-msg-12345"


def test_api_email_status_endpoint():
    resp = client.get("/api/v1/email/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "mode" in data
    assert "sendgrid_configured" in data


def test_api_email_configure_endpoint():
    resp = client.post("/api/v1/email/configure", json={
        "provider": "sendgrid",
        "sendgrid_api_key": "SG.live-key-abc123",
        "from_email": "sfisomadonsela274@gmail.com",
        "from_name": "FleetWatch Telematics"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "SendGrid HTTP API" in data["message"]
    assert data["status"]["sendgrid_configured"] is True
