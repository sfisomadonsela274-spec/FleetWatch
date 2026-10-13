import pytest
from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)

def test_sars_diesel_rebate_json():
    response = client.get("/api/v1/reports/sars-diesel-rebate")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "haulier" in data
    assert data["haulier"]["vat_number"] == "4890214890"
    assert "summary" in data
    assert data["summary"]["sars_rebate_tariff_zar"] == 3.85
    assert "records" in data
    assert len(data["records"]) > 0
    # Verify line item attributes
    first = data["records"][0]
    assert "truck_reg" in first
    assert "cert_hash" in first
    assert first["cert_hash"].startswith("SARS-N4-")

def test_sars_diesel_rebate_csv():
    response = client.get("/api/v1/reports/sars-diesel-rebate/csv")
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    assert "sars_schedule_6_diesel_rebate_2026.csv" in response.headers["content-disposition"]
    content = response.text
    assert "SOUTH AFRICAN REVENUE SERVICE (SARS)" in content
    assert "SECTION 75.03 / SCHEDULE 6 DIESEL REFUND" in content
    assert "VAT / Client Reference,4890214890" in content

def test_rtms_compliance_audit_json():
    response = client.get("/api/v1/reports/rtms-audit")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "SANS 1395" in data["standard"]
    assert "pillar_summary" in data
    assert "vehicles" in data
    assert len(data["vehicles"]) > 0
    v = data["vehicles"][0]
    assert "fatigue_pillar_status" in v
    assert "corridor_geofence_status" in v
    assert "sans1395_score" in v

def test_rtms_compliance_audit_csv():
    response = client.get("/api/v1/reports/rtms-audit/csv")
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    assert "rtms_compliance_audit_sans1395.csv" in response.headers["content-disposition"]
    content = response.text
    assert "ROAD TRANSPORT MANAGEMENT SYSTEM (RTMS) - SANS 1395" in content
    assert "Pillar 1: Fatigue Management" in content
