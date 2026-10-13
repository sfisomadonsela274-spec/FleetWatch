import asyncio
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from backend.main import app
from backend.config import settings

client = TestClient(app)
TOKEN = settings.BEARER_TOKEN
AUTH_HEADER = {"Authorization": f"Bearer {TOKEN}"}

def test_healthcheck():
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "HEALTHY"
    assert data["active_units"] >= 0
    assert "service" in data
    print("✅ Healthcheck verified:", data["service"])

def test_auth_enforcement():
    # Without token
    resp = client.post("/api/v1/telemetry/ping", json={
        "driver_id": "DRV-01",
        "truck_reg": "WP 889 GP",
        "lat": -25.76162,
        "lng": 28.53222,
        "speed_kmh": 70.0
    })
    assert resp.status_code == 401
    print("✅ Unauthorized ping rejected with 401")

def test_normal_n4_ping():
    resp = client.post("/api/v1/telemetry/ping", json={
        "driver_id": "DRV-01",
        "truck_reg": "WP 889 GP",
        "lat": -25.76162,
        "lng": 28.53222,
        "speed_kmh": 72.0,
        "battery_pct": 92,
        "is_charging": True
    }, headers=AUTH_HEADER)
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["distance_from_corridor_m"] <= 300
    print("✅ Normal N4 ping processed! Zone:", data["current_zone"], "| Lateral offset:", data["distance_from_corridor_m"], "m")

def test_rule1_balmoral_detour_alert():
    # Diversion into Balmoral R104 dirt bypass
    resp = client.post("/api/v1/telemetry/ping", json={
        "driver_id": "DRV-01",
        "truck_reg": "WP 889 GP",
        "lat": -25.8350,
        "lng": 28.8950,
        "speed_kmh": 45.0,
        "battery_pct": 85,
        "is_charging": True
    }, headers=AUTH_HEADER)
    assert resp.status_code == 200
    data = resp.json()
    assert data["corridor_status"] == "UNAUTHORIZED_DETOUR"
    assert any(a["type"] == "UNAUTHORIZED_TOLL_BYPASS" for a in data["alerts"])
    print("✅ Rule 1 verified! Toll evasion bypass detected:", data["alerts"][0]["title"])

def test_rule2_fatigue_governor():
    # Send continuous driving exceedance
    now = datetime.now(timezone.utc)
    # Ping 1: high speed
    client.post("/api/v1/telemetry/ping", json={
        "driver_id": "DRV-FATIGUE",
        "truck_reg": "FT 999 GP",
        "lat": -25.76162,
        "lng": 28.53222,
        "speed_kmh": 78.0,
        "timestamp": (now - timedelta(minutes=245)).isoformat()
    }, headers=AUTH_HEADER)

    resp = client.post("/api/v1/telemetry/ping", json={
        "driver_id": "DRV-FATIGUE",
        "truck_reg": "FT 999 GP",
        "lat": -25.76162,
        "lng": 28.53222,
        "speed_kmh": 78.0,
        "timestamp": now.isoformat()
    }, headers=AUTH_HEADER)
    assert resp.status_code == 200
    data = resp.json()
    assert any(a["type"] == "FATIGUE_LIMIT_EXCEEDED" for a in data["alerts"])
    print("✅ Rule 2 verified! Fatigue limit exceeded alert triggered")

def test_rule3_transit_phone_cutoff():
    now = datetime.now(timezone.utc)
    # First ping moving
    client.post("/api/v1/telemetry/ping", json={
        "driver_id": "DRV-CUTOFF",
        "truck_reg": "CT 888 GP",
        "lat": -25.76162,
        "lng": 28.53222,
        "speed_kmh": 82.0,
        "timestamp": (now - timedelta(seconds=150)).isoformat()
    }, headers=AUTH_HEADER)

    # Second ping after 150 seconds gap
    resp = client.post("/api/v1/telemetry/ping", json={
        "driver_id": "DRV-CUTOFF",
        "truck_reg": "CT 888 GP",
        "lat": -25.76500,
        "lng": 28.54000,
        "speed_kmh": 82.0,
        "timestamp": now.isoformat()
    }, headers=AUTH_HEADER)
    assert resp.status_code == 200
    data = resp.json()
    assert any(a["type"] == "PHONE_OFFLINE_IN_TRANSIT" for a in data["alerts"])
    print("✅ Rule 3 verified! Transit phone cutoff detected:", data["alerts"][0]["title"])

def test_offline_store_and_forward_batch():
    now = datetime.now(timezone.utc)
    batch_pings = []
    for i in range(20):
        t = now - timedelta(seconds=30 * (20 - i))
        batch_pings.append({
            "driver_id": "DRV-OFFLINE-RECONNECT",
            "truck_reg": "RC 777 GP",
            "lat": -25.76162 + (i * 0.001),
            "lng": 28.53222 + (i * 0.002),
            "speed_kmh": 70.0 + (i % 5),
            "battery_pct": 90 - (i % 3),
            "is_charging": True,
            "timestamp": t.isoformat()
        })
    
    resp = client.post("/api/v1/telemetry/batch", json={"pings": batch_pings}, headers=AUTH_HEADER)
    assert resp.status_code == 200
    data = resp.json()
    assert data["pings_processed"] == 20
    print("✅ Offline mobile queue drainage verified! Drained 20 pings in batch")

def test_fleet_units_and_alert_resolution():
    resp = client.get("/api/v1/fleet/units")
    assert resp.status_code == 200
    units = resp.json()["units"]
    assert len(units) >= 4
    
    alerts_resp = client.get("/api/v1/fleet/alerts")
    assert alerts_resp.status_code == 200
    alerts = alerts_resp.json()["alerts"]
    if alerts:
        aid = alerts[0]["alert_id"]
        res = client.post(f"/api/v1/fleet/alerts/{aid}/resolve")
        assert res.status_code == 200
        print("✅ Alert resolved successfully:", aid)

if __name__ == "__main__":
    print("\n--- RUNNING FLEETSENTINEL CLOUD BACKEND TEST SUITE ---\n")
    test_healthcheck()
    test_auth_enforcement()
    test_normal_n4_ping()
    test_rule1_balmoral_detour_alert()
    test_rule2_fatigue_governor()
    test_rule3_transit_phone_cutoff()
    test_offline_store_and_forward_batch()
    test_fleet_units_and_alert_resolution()
    print("\n🎉 ALL TESTS PASSED SUCCESSFULLY!\n")
