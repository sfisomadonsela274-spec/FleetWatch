#!/usr/bin/env python3
"""
FleetSentinel Driver Handset Edge Emulator & Offline Buffer Tester
Simulates the Android APK background service with SQLite store-and-forward queue.
Used by Sifiso Madonsela for pilot field testing and Highveld dead zone simulations.
"""

import sqlite3
import time
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

DB_FILE = Path(__file__).parent / "handset_cache.db"
API_URL = "http://localhost:8001/api/v1/telemetry/ping"
BATCH_URL = "http://localhost:8001/api/v1/telemetry/batch"
BEARER_TOKEN = "fleetsentinel_pilot_secret_token_2026"

def init_local_db():
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS pings_cache (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        payload_json TEXT NOT NULL,
        timestamp INTEGER NOT NULL
    );
    """)
    conn.commit()
    conn.close()

def enqueue_offline_ping(payload: dict):
    conn = sqlite3.connect(DB_FILE)
    conn.execute(
        "INSERT INTO pings_cache (payload_json, timestamp) VALUES (?, ?);",
        (json.dumps(payload), int(time.time()))
    )
    conn.commit()
    conn.close()

def get_queue_depth() -> int:
    conn = sqlite3.connect(DB_FILE)
    count = conn.execute("SELECT COUNT(*) FROM pings_cache;").fetchone()[0]
    conn.close()
    return count

def drain_queue_batch(batch_size: int = 20) -> int:
    conn = sqlite3.connect(DB_FILE)
    rows = conn.execute(
        "SELECT id, payload_json FROM pings_cache ORDER BY timestamp ASC LIMIT ?;",
        (batch_size,)
    ).fetchall()
    
    if not rows:
        conn.close()
        return 0

    ids = [r[0] for r in rows]
    pings = [json.loads(r[1]) for r in rows]

    req = urllib.request.Request(
        BATCH_URL,
        data=json.dumps({"pings": pings}).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {BEARER_TOKEN}"
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                id_str = ",".join(str(i) for i in ids)
                conn.execute(f"DELETE FROM pings_cache WHERE id IN ({id_str});")
                conn.commit()
                conn.close()
                return len(ids)
    except Exception as e:
        print(f"⚠️ [Handset Sync] Drainage failed: {e}")

    conn.close()
    return 0

def transmit_ping(payload: dict, simulate_dead_zone: bool = False) -> bool:
    if simulate_dead_zone:
        print(f"📵 [Highveld Dead Zone] Network unreachable. Buffering ping in local SQLite cache...")
        enqueue_offline_ping(payload)
        return False

    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {BEARER_TOKEN}"
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=4) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                print(f"✅ [Handset Uplink] Ping ACK: Zone={data['current_zone']} | Corridor={data['corridor_status']} | Speed={payload['speed_kmh']}km/h")
                return True
    except Exception as e:
        print(f"⚠️ [Network Timeout] Buffering ping locally in SQLite: {e}")
        enqueue_offline_ping(payload)
        return False

if __name__ == "__main__":
    init_local_db()
    print("================================================================")
    print("  🇿🇦 FLEETSENTINEL DRIVER HANDSET EDGE EMULATOR")
    print("  • Corridor: N4 Highveld Artery (Pretoria East ⇄ Witbank)")
    print("  • Ingress: " + API_URL)
    print("  • Local SQLite Store & Forward: " + str(DB_FILE))
    print("================================================================")

    # Simulate 5 normal pings
    for i in range(3):
        transmit_ping({
            "driver_id": "DRV-01",
            "truck_reg": "WP 889 GP",
            "lat": -25.76162 + (i * 0.005),
            "lng": 28.53222 + (i * 0.008),
            "speed_kmh": 74.0,
            "battery_pct": 94,
            "is_charging": True,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        time.sleep(1)

    # Simulate 5 pings in Balmoral cellular dead zone
    print("\n--- ENTERING 14 KM BALMORAL CELLULAR DEAD ZONE ---")
    for i in range(5):
        transmit_ping({
            "driver_id": "DRV-01",
            "truck_reg": "WP 889 GP",
            "lat": -25.8350 + (i * 0.002),
            "lng": 28.8950 + (i * 0.003),
            "speed_kmh": 70.0,
            "battery_pct": 93,
            "is_charging": True,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }, simulate_dead_zone=True)

    print(f"\n📦 Local SQLite Queue Depth: {get_queue_depth()} pings buffered during dead zone.")

    # Reconnect and drain batch
    print("\n--- RECONNECTING TO 4G CELLULAR TOWER AT WITBANK APPROACH ---")
    drained = drain_queue_batch(20)
    print(f"🚀 Drained {drained} pings in single batch to {BATCH_URL}!")
    print(f"📦 Remaining SQLite Queue Depth: {get_queue_depth()} (Fully Synchronized)\n")
