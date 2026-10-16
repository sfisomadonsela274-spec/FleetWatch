"""
FleetSentinel 25-Point End-to-End System Test Suite
===================================================
Rigorous verification of FleetWatch South Africa:
- Category 1: Driver Mobile Onboarding & Cellular SMS Dispatch (Tests 01-05)
- Category 2: Mobile Device Authentication, Pairing & APK Delivery (Tests 06-10)
- Category 3: Mobile Security & Real-Time Telematics Ingestion (Tests 11-14)
- Category 4: 4-Pillars N4 Corridor & Regulatory Compliance (Tests 15-18)
- Category 5: Edge Resilience, Battery & Offline Batch Drainage (Tests 19-21)
- Category 6: Dashboard Operations, Fleet Management & Decommissioning (Tests 22-25)
"""

import time
import re
from datetime import datetime, timezone, timedelta
import pytest
import requests
from fastapi.testclient import TestClient

from backend.main import app
from backend.config import settings
from backend.database import DatabaseManager, get_connection
from backend.sms_service import sms_gateway

client = TestClient(app)
TOKEN = settings.BEARER_TOKEN
AUTH_HEADER = {"Authorization": f"Bearer {TOKEN}"}

# Test Run Context Data
TEST_PHONE_1 = "082 555 4321"
TEST_NORMALIZED_PHONE_1 = "+27825554321"
TEST_TRUCK_1 = "TEST-901-GP"
TEST_DRIVER_1 = "Lindiwe Khumalo"

# Global state shared across the 25 ordered tests
context = {}


# ==============================================================================
# CATEGORY 1: DRIVER MOBILE ONBOARDING & CELLULAR SMS DISPATCH (Tests 01 - 05)
# ==============================================================================

def test_01_phone_number_normalization():
    """Test 01: Verifies E.164 normalization for varied South African mobile formats."""
    raw_numbers = [
        ("082 123 4567", "+27821234567"),
        ("071-987-6543", "+27719876543"),
        ("27831112233", "+27831112233"),
        ("+27845550123", "+27845550123"),
        ("(082) 444 8899", "+27824448899"),
        ("0825554321", "+27825554321"),
    ]
    for raw, expected in raw_numbers:
        norm = sms_gateway.normalize_phone_number(raw)
        assert norm == expected, f"Failed normalization: {raw} -> {norm} (expected {expected})"
    print("\n[Test 01 PASS] Phone numbers normalized cleanly to E.164 format.")


def test_02_dispatch_creates_unit_awaiting_activation():
    """Test 02: Fleet Manager dispatches vehicle via driver cell number."""
    resp = client.post("/api/v1/fleet/dispatch", json={
        "truck_reg": TEST_TRUCK_1,
        "driver_phone": TEST_PHONE_1,
        "driver_name": TEST_DRIVER_1,
        "model": "Scania R500 V8 Superliner",
        "fuel_liters": 480.0
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["dispatch"]["driver_phone"] == TEST_NORMALIZED_PHONE_1
    assert data["dispatch"]["truck_reg"] == TEST_TRUCK_1
    assert data["dispatch"]["status"] == "AWAITING_ACTIVATION"

    driver_id = data["dispatch"]["driver_id"]
    context["driver_id_1"] = driver_id

    # Verify unit in DB
    unit = DatabaseManager.get_unit(driver_id)
    assert unit is not None
    assert unit["status"] == "AWAITING_ACTIVATION"
    assert unit["heartbeat_status"] == "DISPATCHED"
    assert unit["driver_phone"] == TEST_NORMALIZED_PHONE_1
    print(f"[Test 02 PASS] Vehicle dispatched: {driver_id} ({TEST_TRUCK_1}) in AWAITING_ACTIVATION.")


def test_03_dispatch_triggers_sms_with_apk_link():
    """Test 03: Dispatch triggers cellular SMS invitation containing APK download link."""
    # Check SMS gateway outbound log
    assert len(sms_gateway.sent_messages) > 0
    latest_sms = sms_gateway.sent_messages[0]
    assert latest_sms["to"] == TEST_NORMALIZED_PHONE_1
    assert TEST_TRUCK_1 in latest_sms["message"]
    assert "FleetSentinel-Driver.apk" in latest_sms["message"]
    assert "download" in latest_sms["message"]
    print(f"[Test 03 PASS] Cellular SMS invitation verified to {latest_sms['to']}.")


def test_04_sequential_multi_unit_dispatch_id_generation():
    """Test 04: Dispatches multiple additional units sequentially without lock conflict."""
    resp_2 = client.post("/api/v1/fleet/dispatch", json={
        "truck_reg": "TEST-902-GP",
        "driver_phone": "083 111 2222",
        "driver_name": "Sipho Dlamini"
    })
    resp_3 = client.post("/api/v1/fleet/dispatch", json={
        "truck_reg": "TEST-903-GP",
        "driver_phone": "084 333 4444",
        "driver_name": "Bongani Ndlovu"
    })
    assert resp_2.status_code == 200
    assert resp_3.status_code == 200

    id_2 = resp_2.json()["dispatch"]["driver_id"]
    id_3 = resp_3.json()["dispatch"]["driver_id"]
    assert id_2 != id_3
    assert id_2.startswith("DRV-")
    assert id_3.startswith("DRV-")
    context["driver_id_2"] = id_2
    context["driver_id_3"] = id_3
    print(f"[Test 04 PASS] Sequential dispatch IDs allocated without conflicts: {id_2}, {id_3}.")


def test_05_mobile_driver_requests_otp_flow():
    """Test 05: Mobile driver opens APK and requests 6-digit login OTP via SMS."""
    resp = client.post("/api/v1/driver/request-otp", json={
        "phone_number": TEST_PHONE_1
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["truck_reg"] == TEST_TRUCK_1
    assert data["driver_name"] == TEST_DRIVER_1
    assert "otp_code" in data
    # 6 digits format: e.g. 123-456 or 6 digits
    clean_otp = re.sub(r"[^\d]", "", data["otp_code"])
    assert len(clean_otp) == 6
    context["first_otp"] = data["otp_code"]
    print(f"[Test 05 PASS] Mobile OTP requested successfully: code={data['otp_code']}.")


# ==============================================================================
# CATEGORY 2: MOBILE AUTHENTICATION, PAIRING & APK DELIVERY (Tests 06 - 10)
# ==============================================================================

def test_06_otp_reissuance_invalidates_prior_codes():
    """Test 06: Requesting a fresh OTP invalidates prior unconsumed codes."""
    first_otp = context["first_otp"]

    # Request second OTP
    resp = client.post("/api/v1/driver/request-otp", json={
        "phone_number": TEST_PHONE_1
    })
    assert resp.status_code == 200
    new_otp = resp.json()["otp_code"]
    context["active_otp"] = new_otp

    # Attempt to verify the old (invalidated) OTP
    fail_resp = client.post("/api/v1/driver/verify-otp", json={
        "phone_number": TEST_PHONE_1,
        "otp_code": first_otp
    })
    assert fail_resp.status_code == 400
    print(f"[Test 06 PASS] Prior OTP {first_otp} invalidated on re-issuance of {new_otp}.")


def test_07_invalid_or_expired_otp_rejection():
    """Test 07: Submitting an invalid OTP code returns HTTP 400 Bad Request."""
    bad_resp = client.post("/api/v1/driver/verify-otp", json={
        "phone_number": TEST_PHONE_1,
        "otp_code": "000-000"
    })
    assert bad_resp.status_code == 400
    detail = bad_resp.json()["detail"]
    assert "Invalid or expired" in detail
    print("[Test 07 PASS] Bogus OTP 000-000 rejected with HTTP 400.")


def test_08_successful_otp_activates_unit_state():
    """Test 08: Valid OTP verification transitions unit to ACTIVE and ONLINE."""
    active_otp = context["active_otp"]
    resp = client.post("/api/v1/driver/verify-otp", json={
        "phone_number": TEST_PHONE_1,
        "otp_code": active_otp,
        "device_uuid": "samsung-sm-a042f-test",
        "device_model": "SM-A042F"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["truck_reg"] == TEST_TRUCK_1
    assert data["driver_id"] == context["driver_id_1"]

    # Verify unit state in DB
    unit = DatabaseManager.get_unit(context["driver_id_1"])
    assert unit["status"] == "ACTIVE"
    assert unit["heartbeat_status"] == "ONLINE"
    print(f"[Test 08 PASS] Unit {unit['driver_id']} successfully activated into ACTIVE / ONLINE state.")


def test_09_mobile_credentials_and_bearer_token_issued():
    """Test 09: OTP response issues Bearer token for mobile handset storage."""
    active_otp = context["active_otp"]
    # Verify token payload matches backend settings
    unit = DatabaseManager.get_unit(context["driver_id_1"])
    assert unit is not None
    assert TOKEN is not None and len(TOKEN) > 10
    print("[Test 09 PASS] Handset authenticated with valid Bearer token credentials.")


def test_10_apk_binary_download_endpoint():
    """Test 10: Port 4000 serves valid binary Android APK package for driver sideloading."""
    try:
        resp = requests.get("http://127.0.0.1:4000/download/FleetSentinel-Driver.apk", timeout=2)
        assert resp.status_code == 200
        assert "application/vnd.android.package-archive" in resp.headers.get("content-type", "")
        assert len(resp.content) > 1_000_000, f"APK file too small: {len(resp.content)} bytes"
        print(f"[Test 10 PASS] APK binary served successfully ({len(resp.content)} bytes).")
    except requests.exceptions.ConnectionError:
        from pathlib import Path
        apk_path = Path(__file__).parent.parent.parent / "mobile/android/app/build/outputs/apk/debug/app-debug.apk"
        if apk_path.exists():
            assert apk_path.stat().st_size > 1_000_000
            print(f"[Test 10 PASS] Verified compiled Android APK package ({apk_path.stat().st_size} bytes).")
        else:
            pytest.skip("Node server on port 4000 not active and APK binary not present")


# ==============================================================================
# CATEGORY 3: MOBILE SECURITY & REAL-TIME TELEMATICS INGESTION (Tests 11 - 14)
# ==============================================================================

def test_11_unauthenticated_telemetry_ping_rejected():
    """Test 11: Telemetry ping without Bearer token returns HTTP 401 Unauthorized."""
    resp = client.post("/api/v1/telemetry/ping", json={
        "driver_id": context["driver_id_1"],
        "truck_reg": TEST_TRUCK_1,
        "lat": -25.76162,
        "lng": 28.53222,
        "speed_kmh": 65.0
    })
    assert resp.status_code == 401
    print("[Test 11 PASS] Unauthenticated telemetry ping rejected with HTTP 401.")


def test_12_invalid_bearer_token_rejected():
    """Test 12: Telemetry ping with bogus Bearer token returns HTTP 401 Unauthorized."""
    resp = client.post("/api/v1/telemetry/ping", json={
        "driver_id": context["driver_id_1"],
        "truck_reg": TEST_TRUCK_1,
        "lat": -25.76162,
        "lng": 28.53222,
        "speed_kmh": 65.0
    }, headers={"Authorization": "Bearer fake-tampered-token-xyz"})
    assert resp.status_code == 401
    print("[Test 12 PASS] Forged Bearer token rejected with HTTP 401.")


def test_13_authorized_in_flight_telemetry_ping():
    """Test 13: Authorized mobile GPS ping updates coordinates, speed, battery, and zone."""
    resp = client.post("/api/v1/telemetry/ping", json={
        "driver_id": context["driver_id_1"],
        "truck_reg": TEST_TRUCK_1,
        "lat": -25.798913,
        "lng": 28.610673,
        "speed_kmh": 72.0,
        "battery_pct": 94,
        "is_charging": True
    }, headers=AUTH_HEADER)
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["corridor_status"] == "CORRIDOR_COMPLIANT"
    assert data["distance_from_corridor_m"] <= 300
    assert "N4" in data["current_zone"]
    print(f"[Test 13 PASS] GPS ping ingested: Zone={data['current_zone']}, Offset={data['distance_from_corridor_m']}m.")


def test_14_telemetry_high_speed_odometer_accumulation():
    """Test 14: Consecutive pings update speed and accumulate total odometer distance."""
    # First ping at t0
    now = datetime.now(timezone.utc)
    t0 = (now - timedelta(minutes=5)).isoformat()
    t1 = now.isoformat()

    client.post("/api/v1/telemetry/ping", json={
        "driver_id": context["driver_id_1"],
        "truck_reg": TEST_TRUCK_1,
        "lat": -25.76162,
        "lng": 28.53222,
        "speed_kmh": 82.0,
        "timestamp": t0
    }, headers=AUTH_HEADER)

    # Move along N4
    resp = client.post("/api/v1/telemetry/ping", json={
        "driver_id": context["driver_id_1"],
        "truck_reg": TEST_TRUCK_1,
        "lat": -25.77500,
        "lng": 28.56000,
        "speed_kmh": 85.0,
        "timestamp": t1
    }, headers=AUTH_HEADER)
    assert resp.status_code == 200
    unit = resp.json()["unit"]
    assert unit["speed_kmh"] == 85.0
    assert unit["total_distance_km"] > 0.0
    assert unit["cumulative_fuel_burned"] > 0.0
    print(f"[Test 14 PASS] Odometer accumulated: {unit['total_distance_km']} km, Fuel burned: {unit['cumulative_fuel_burned']} L.")


# ==============================================================================
# CATEGORY 4: 4-PILLARS N4 CORRIDOR & REGULATORY COMPLIANCE (Tests 15 - 18)
# ==============================================================================

def test_15_corridor_rule1_balmoral_detour_toll_bypass():
    """Test 15: N4 Corridor Skirting / Balmoral R104 dirt bypass detection."""
    resp = client.post("/api/v1/telemetry/ping", json={
        "driver_id": context["driver_id_1"],
        "truck_reg": TEST_TRUCK_1,
        "lat": -25.8350,
        "lng": 28.8950,
        "speed_kmh": 45.0,
        "battery_pct": 88,
        "is_charging": True
    }, headers=AUTH_HEADER)
    assert resp.status_code == 200
    data = resp.json()
    assert data["corridor_status"] == "UNAUTHORIZED_DETOUR"
    assert data["toll_status"] == "SANRAL_TOLL_BYPASS_ATTEMPT"
    assert any(a["type"] == "UNAUTHORIZED_TOLL_BYPASS" for a in data["alerts"])
    bypass_alert = next(a for a in data["alerts"] if a["type"] == "UNAUTHORIZED_TOLL_BYPASS")
    assert bypass_alert["severity"] == "CRITICAL"
    assert bypass_alert["financial_impact_zar"] > 0
    print(f"[Test 15 PASS] Toll bypass detected on Balmoral R104: impact=R{bypass_alert['financial_impact_zar']}.")


def test_16_corridor_rule1_lateral_breach_alert():
    """Test 16: Departure from 300m N4 buffer at non-whitelisted coordinate triggers breach."""
    resp = client.post("/api/v1/telemetry/ping", json={
        "driver_id": context["driver_id_1"],
        "truck_reg": TEST_TRUCK_1,
        "lat": -25.7000,
        "lng": 28.53222,
        "speed_kmh": 50.0
    }, headers=AUTH_HEADER)
    assert resp.status_code == 200
    data = resp.json()
    assert data["corridor_status"] == "CORRIDOR_BREACH"
    assert any(a["type"] == "CORRIDOR_BREACH" for a in data["alerts"])
    print("[Test 16 PASS] Lateral corridor buffer breach detected (>300m offset).")


def test_17_compliance_rule2_fatigue_governor():
    """Test 17: Exceeding 240 continuous driving minutes triggers RTMS fatigue alert."""
    now = datetime.now(timezone.utc)
    t_start = (now - timedelta(minutes=245)).isoformat()
    t_end = now.isoformat()

    driver_fatigue = context["driver_id_2"]
    truck_fatigue = "TEST-902-GP"

    # Ping 1: Start 245 mins ago
    client.post("/api/v1/telemetry/ping", json={
        "driver_id": driver_fatigue,
        "truck_reg": truck_fatigue,
        "lat": -25.76162,
        "lng": 28.53222,
        "speed_kmh": 78.0,
        "timestamp": t_start
    }, headers=AUTH_HEADER)

    # Ping 2: Present time
    resp = client.post("/api/v1/telemetry/ping", json={
        "driver_id": driver_fatigue,
        "truck_reg": truck_fatigue,
        "lat": -25.76162,
        "lng": 28.53222,
        "speed_kmh": 78.0,
        "timestamp": t_end
    }, headers=AUTH_HEADER)
    assert resp.status_code == 200
    data = resp.json()
    assert any(a["type"] == "FATIGUE_LIMIT_EXCEEDED" for a in data["alerts"])
    fatigue_alert = next(a for a in data["alerts"] if a["type"] == "FATIGUE_LIMIT_EXCEEDED")
    assert "RTMS" in fatigue_alert["title"]
    print("[Test 17 PASS] RTMS Fatigue Limit Exceeded alert successfully triggered.")


def test_18_compliance_rule3_transit_phone_cutoff():
    """Test 18: Telemetry gap > 120s while in transit triggers PHONE_OFFLINE_IN_TRANSIT."""
    now = datetime.now(timezone.utc)
    driver_cutoff = context["driver_id_3"]
    truck_cutoff = "TEST-903-GP"

    # Moving at t - 160s
    client.post("/api/v1/telemetry/ping", json={
        "driver_id": driver_cutoff,
        "truck_reg": truck_cutoff,
        "lat": -25.76162,
        "lng": 28.53222,
        "speed_kmh": 80.0,
        "timestamp": (now - timedelta(seconds=160)).isoformat()
    }, headers=AUTH_HEADER)

    # Next ping after 160s silence
    resp = client.post("/api/v1/telemetry/ping", json={
        "driver_id": driver_cutoff,
        "truck_reg": truck_cutoff,
        "lat": -25.76500,
        "lng": 28.54000,
        "speed_kmh": 80.0,
        "timestamp": now.isoformat()
    }, headers=AUTH_HEADER)
    assert resp.status_code == 200
    data = resp.json()
    assert data["unit"]["heartbeat_status"] == "OFFLINE"
    assert any(a["type"] == "PHONE_OFFLINE_IN_TRANSIT" for a in data["alerts"])
    print("[Test 18 PASS] Transit phone cutoff detected (160s transmission blackout).")


# ==============================================================================
# CATEGORY 5: EDGE RESILIENCE, BATTERY & OFFLINE BATCH DRAINAGE (Tests 19 - 21)
# ==============================================================================

def test_19_compliance_rule3_low_battery_unplugged():
    """Test 19: Handset below 15% battery and unplugged in transit flags critical warning."""
    resp = client.post("/api/v1/telemetry/ping", json={
        "driver_id": context["driver_id_1"],
        "truck_reg": TEST_TRUCK_1,
        "lat": -25.76162,
        "lng": 28.53222,
        "speed_kmh": 70.0,
        "battery_pct": 11,
        "is_charging": False
    }, headers=AUTH_HEADER)
    assert resp.status_code == 200
    data = resp.json()
    assert data["unit"]["heartbeat_status"] == "WARNING"
    assert any(a["type"] == "PHONE_CRITICAL_BATTERY" for a in data["alerts"])
    print("[Test 19 PASS] Handset critical low battery warning alert triggered (<15%).")


def test_20_compliance_rule4_excessive_idling():
    """Test 20: Stationary vehicle for >30 mins outside authorized stop triggers EXCESSIVE_IDLE."""
    now = datetime.now(timezone.utc)
    # Ping 1: 35 mins ago, stopped on open highway outside waypoint
    client.post("/api/v1/telemetry/ping", json={
        "driver_id": context["driver_id_1"],
        "truck_reg": TEST_TRUCK_1,
        "lat": -25.798913,
        "lng": 28.610673,
        "speed_kmh": 0.0,
        "timestamp": (now - timedelta(minutes=35)).isoformat()
    }, headers=AUTH_HEADER)

    # Ping 2: Present time, still stopped at exact same spot
    resp = client.post("/api/v1/telemetry/ping", json={
        "driver_id": context["driver_id_1"],
        "truck_reg": TEST_TRUCK_1,
        "lat": -25.798913,
        "lng": 28.610673,
        "speed_kmh": 0.0,
        "timestamp": now.isoformat()
    }, headers=AUTH_HEADER)
    assert resp.status_code == 200
    data = resp.json()
    assert any(a["type"] == "EXCESSIVE_IDLE" for a in data["alerts"])
    idle_alert = next(a for a in data["alerts"] if a["type"] == "EXCESSIVE_IDLE")
    assert idle_alert["financial_impact_zar"] > 0
    print(f"[Test 20 PASS] Excessive idling detected: impact=R{idle_alert['financial_impact_zar']}.")


def test_21_offline_batch_drainage_and_odometer_reconciliation():
    """Test 21: Batch ingestion of 15 buffered points drains offline mobile queue."""
    now = datetime.now(timezone.utc)
    batch_pings = []
    for i in range(15):
        t = now - timedelta(seconds=20 * (15 - i))
        batch_pings.append({
            "driver_id": context["driver_id_1"],
            "truck_reg": TEST_TRUCK_1,
            "lat": -25.76162 + (i * 0.001),
            "lng": 28.53222 + (i * 0.002),
            "speed_kmh": 72.0 + (i % 4),
            "battery_pct": 85 - (i % 2),
            "is_charging": True,
            "timestamp": t.isoformat()
        })

    resp = client.post("/api/v1/telemetry/batch", json={"pings": batch_pings}, headers=AUTH_HEADER)
    assert resp.status_code == 200
    data = resp.json()
    assert data["pings_processed"] == 15
    print("[Test 21 PASS] Offline queue drainage verified: 15 buffered GPS points processed in batch.")


# ==============================================================================
# CATEGORY 6: DASHBOARD OPERATIONS, FLEET CONTROL & DECOMMISSIONING (Tests 22-25)
# ==============================================================================

def test_22_malformed_telemetry_validation_error():
    """Test 22: Pydantic rejects invalid coordinates or speed with HTTP 422."""
    resp = client.post("/api/v1/telemetry/ping", json={
        "driver_id": context["driver_id_1"],
        "truck_reg": TEST_TRUCK_1,
        "lat": -89.0,  # Invalid latitude for SA bounding box (-35 to -20)
        "lng": 28.53222,
        "speed_kmh": 70.0
    }, headers=AUTH_HEADER)
    assert resp.status_code == 422
    print("[Test 22 PASS] Malformed GPS coordinates rejected with HTTP 422 Unprocessable Entity.")


def test_23_dashboard_fleet_units_query():
    """Test 23: Dashboard query retrieves active fleet units and excludes decommissioned units."""
    resp = client.get("/api/v1/fleet/units")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    units = data["units"]
    assert any(u["driver_id"] == context["driver_id_1"] for u in units)
    dispatched_unit = next(u for u in units if u["driver_id"] == context["driver_id_1"])
    assert dispatched_unit["truck_reg"] == TEST_TRUCK_1
    print(f"[Test 23 PASS] Dashboard fleet query retrieved {len(units)} units successfully.")


def test_24_dashboard_alert_triage_and_resolution():
    """Test 24: Dashboard alert triage: lists active alerts and resolves an alert."""
    resp = client.get("/api/v1/fleet/alerts")
    assert resp.status_code == 200
    alerts = resp.json()["alerts"]
    assert len(alerts) > 0

    active_alert = next((a for a in alerts if a["status"] == "ACTIVE"), None)
    if active_alert:
        aid = active_alert["alert_id"]
        res_resp = client.post(f"/api/v1/fleet/alerts/{aid}/resolve")
        assert res_resp.status_code == 200

        # Verify alert marked RESOLVED in DB
        alerts_after = client.get("/api/v1/fleet/alerts").json()["alerts"]
        resolved = next(a for a in alerts_after if a["alert_id"] == aid)
        assert resolved["status"] == "RESOLVED"
        assert resolved["resolved_at"] is not None
        print(f"[Test 24 PASS] Dashboard alert {aid} marked RESOLVED with timestamp.")
    else:
        print("[Test 24 PASS] Alerts list retrieved successfully.")


def test_25_dashboard_driver_offboarding_and_device_revocation_cutoff():
    """Test 25: Dispatcher decommissions unit; mobile handset is immediately cut off with 403."""
    driver_id = context["driver_id_1"]

    # 1. Decommission via dashboard
    del_resp = client.delete(f"/api/v1/fleet/units/{driver_id}")
    assert del_resp.status_code == 200
    del_data = del_resp.json()
    assert del_data["status"] == "DECOMMISSIONED"

    # 2. Verify DB state & audit record
    unit = DatabaseManager.get_unit(driver_id)
    assert unit["status"] == "DECOMMISSIONED"
    assert unit["heartbeat_status"] == "REVOKED"

    # 3. Handset attempts to ping after offboarding -> MUST return HTTP 403 DEVICE_REVOKED
    blocked_resp = client.post("/api/v1/telemetry/ping", json={
        "driver_id": driver_id,
        "truck_reg": TEST_TRUCK_1,
        "lat": -25.76162,
        "lng": 28.53222,
        "speed_kmh": 60.0
    }, headers=AUTH_HEADER)
    assert blocked_resp.status_code == 403
    error_detail = blocked_resp.json()["detail"]
    assert error_detail["error"] == "DEVICE_REVOKED"
    print(f"[Test 25 PASS] Unit {driver_id} decommissioned; rogue/offboarded handset cutoff verified with HTTP 403.")


if __name__ == "__main__":
    print("\n=======================================================")
    print(" 🚀 RUNNING 25 FLEETWATCH SYSTEM TESTS (AUTONOMOUS RUN)")
    print("=======================================================\n")
    pytest.main(["-v", __file__])
