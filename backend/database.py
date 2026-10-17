import sqlite3
import os
import json
from datetime import datetime, timezone
from pathlib import Path

DB_FILE = Path(__file__).parent / "fleetsentinel.db"

def get_connection():
    conn = sqlite3.connect(DB_FILE, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # Enable WAL mode for high concurrency
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout = 30000;")
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    
    # 1. Hot State: fleet_units
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS fleet_units (
        driver_id TEXT PRIMARY KEY,
        truck_reg TEXT NOT NULL,
        driver_name TEXT,
        driver_phone TEXT NOT NULL DEFAULT '',
        driver_email TEXT NOT NULL DEFAULT '',
        model TEXT,
        lat REAL NOT NULL,
        lng REAL NOT NULL,
        speed_kmh REAL NOT NULL DEFAULT 0.0,
        battery_pct INTEGER NOT NULL DEFAULT 100,
        is_charging INTEGER NOT NULL DEFAULT 1,
        continuous_drive_mins INTEGER NOT NULL DEFAULT 0,
        idle_minutes INTEGER NOT NULL DEFAULT 0,
        last_ping_time TEXT NOT NULL,
        toll_status TEXT NOT NULL DEFAULT 'N4_CLEAR',
        corridor_status TEXT NOT NULL DEFAULT 'CORRIDOR_COMPLIANT',
        current_zone TEXT NOT NULL DEFAULT 'Pretoria East Depot',
        distance_from_corridor_m REAL NOT NULL DEFAULT 0.0,
        heartbeat_status TEXT NOT NULL DEFAULT 'ONLINE',
        total_distance_km REAL NOT NULL DEFAULT 0.0,
        fuel_remaining_liters REAL NOT NULL DEFAULT 480.0,
        cumulative_fuel_burned REAL NOT NULL DEFAULT 0.0,
        status TEXT NOT NULL DEFAULT 'ACTIVE'
    );
    """)

    # 2. Append-Only Exception Ledger: alerts_log
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS alerts_log (
        alert_id TEXT PRIMARY KEY,
        driver_id TEXT NOT NULL,
        truck_reg TEXT NOT NULL,
        type TEXT NOT NULL,
        severity TEXT NOT NULL,
        title TEXT NOT NULL,
        description TEXT NOT NULL,
        lat REAL,
        lng REAL,
        financial_impact_zar REAL NOT NULL DEFAULT 0.0,
        created_at TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'ACTIVE',
        resolved_at TEXT
    );
    """)

    # 3. Dynamic Driver Pairing & Handset Onboarding Tokens
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS pairing_tokens (
        pin TEXT PRIMARY KEY,
        driver_id TEXT NOT NULL,
        truck_reg TEXT NOT NULL,
        driver_name TEXT NOT NULL,
        driver_phone TEXT,
        driver_email TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        is_used INTEGER NOT NULL DEFAULT 0
    );
    """)

    # 4. Cellular SMS & Email OTP Verification Codes
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS driver_otps (
        phone_number TEXT NOT NULL DEFAULT '',
        driver_email TEXT NOT NULL DEFAULT '',
        otp_code TEXT NOT NULL,
        driver_id TEXT NOT NULL,
        truck_reg TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        is_used INTEGER NOT NULL DEFAULT 0
    );
    """)

    # 5. Schema Migrations for Legacy / Pre-existing Databases
    migrations = [
        ("fleet_units", "status", "TEXT NOT NULL DEFAULT 'ACTIVE'"),
        ("fleet_units", "driver_phone", "TEXT NOT NULL DEFAULT ''"),
        ("fleet_units", "driver_email", "TEXT NOT NULL DEFAULT ''"),
        ("driver_otps", "driver_email", "TEXT NOT NULL DEFAULT ''"),
        ("driver_otps", "phone_number", "TEXT NOT NULL DEFAULT ''"),
        ("pairing_tokens", "driver_email", "TEXT NOT NULL DEFAULT ''")
    ]
    for table, col, col_def in migrations:
        try:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_def};")
        except sqlite3.OperationalError:
            pass
    
    # Create indexes for fast lookups
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_alerts_driver ON alerts_log(driver_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_alerts_created ON alerts_log(created_at);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts_log(status);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pairing_pin ON pairing_tokens(pin);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_otp_phone ON driver_otps(phone_number);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_otp_email ON driver_otps(driver_email);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_otp_code ON driver_otps(otp_code);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_units_phone ON fleet_units(driver_phone);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_units_email ON fleet_units(driver_email);")

    conn.commit()
    conn.close()

# Initialize tables on import
init_db()

class DatabaseManager:
    @staticmethod
    def get_unit(driver_id: str) -> dict | None:
        conn = get_connection()
        query = """
            SELECT f.*, o.otp_code
            FROM fleet_units f
            LEFT JOIN (
                SELECT driver_id, otp_code, MAX(created_at)
                FROM driver_otps
                WHERE is_used = 0
                GROUP BY driver_id
            ) o ON f.driver_id = o.driver_id
            WHERE f.driver_id = ?;
        """
        row = conn.execute(query, (driver_id,)).fetchone()
        conn.close()
        return dict(row) if row else None

    @staticmethod
    def get_all_units(include_decommissioned: bool = False) -> list[dict]:
        conn = get_connection()
        where_clause = "" if include_decommissioned else "WHERE f.status != 'DECOMMISSIONED'"
        query = f"""
            SELECT f.*, o.otp_code
            FROM fleet_units f
            LEFT JOIN (
                SELECT driver_id, otp_code, MAX(created_at)
                FROM driver_otps
                WHERE is_used = 0
                GROUP BY driver_id
            ) o ON f.driver_id = o.driver_id
            {where_clause}
            ORDER BY f.driver_id ASC;
        """
        rows = conn.execute(query).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    @staticmethod
    def upsert_unit(data: dict):
        conn = get_connection()
        unit_status = data.get("status", "ACTIVE")
        data_with_status = {**data, "status": unit_status}
        conn.execute("""
        INSERT INTO fleet_units (
            driver_id, truck_reg, driver_name, model, lat, lng, speed_kmh, battery_pct, is_charging,
            continuous_drive_mins, idle_minutes, last_ping_time, toll_status, corridor_status,
            current_zone, distance_from_corridor_m, heartbeat_status, total_distance_km,
            fuel_remaining_liters, cumulative_fuel_burned, status
        ) VALUES (
            :driver_id, :truck_reg, :driver_name, :model, :lat, :lng, :speed_kmh, :battery_pct, :is_charging,
            :continuous_drive_mins, :idle_minutes, :last_ping_time, :toll_status, :corridor_status,
            :current_zone, :distance_from_corridor_m, :heartbeat_status, :total_distance_km,
            :fuel_remaining_liters, :cumulative_fuel_burned, :status
        )
        ON CONFLICT(driver_id) DO UPDATE SET
            truck_reg = excluded.truck_reg,
            lat = excluded.lat,
            lng = excluded.lng,
            speed_kmh = excluded.speed_kmh,
            battery_pct = excluded.battery_pct,
            is_charging = excluded.is_charging,
            continuous_drive_mins = excluded.continuous_drive_mins,
            idle_minutes = excluded.idle_minutes,
            last_ping_time = excluded.last_ping_time,
            toll_status = excluded.toll_status,
            corridor_status = excluded.corridor_status,
            current_zone = excluded.current_zone,
            distance_from_corridor_m = excluded.distance_from_corridor_m,
            heartbeat_status = excluded.heartbeat_status,
            total_distance_km = excluded.total_distance_km,
            fuel_remaining_liters = excluded.fuel_remaining_liters,
            cumulative_fuel_burned = excluded.cumulative_fuel_burned;
        """, data_with_status)
        conn.commit()
        conn.close()
    @staticmethod
    def dispatch_unit(
        truck_reg: str,
        driver_phone: str = "",
        driver_name: str = "Driver",
        model: str = "Scania R500 V8",
        fuel_liters: float = 450.0,
        driver_email: str = ""
    ) -> dict:
        import random
        from datetime import timedelta
        from .sms_service import sms_gateway
        conn = get_connection()
        cursor = conn.cursor()

        normalized_phone = sms_gateway.normalize_phone_number(driver_phone) if driver_phone else ""
        clean_email = driver_email.strip().lower()

        # Generate next driver_id
        cursor.execute("SELECT driver_id FROM fleet_units WHERE driver_id LIKE 'DRV-%';")
        rows = cursor.fetchall()
        max_num = 0
        for r in rows:
            try:
                num = int(r["driver_id"].replace("DRV-", ""))
                if num > max_num:
                    max_num = num
            except Exception:
                pass
        driver_id = f"DRV-{str(max_num + 1).zfill(2)}"

        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        expires_at = (now + timedelta(hours=24)).isoformat()

        # Generate 6-digit In-Cab OTP Code immediately on dispatch
        otp_num = random.randint(100000, 999999)
        raw_otp = str(otp_num)
        formatted_otp = f"{raw_otp[:3]}-{raw_otp[3:]}"

        # Insert unit in AWAITING_ACTIVATION status
        cursor.execute("""
        INSERT INTO fleet_units (
            driver_id, truck_reg, driver_name, driver_phone, driver_email, model, lat, lng, speed_kmh, battery_pct, is_charging,
            continuous_drive_mins, idle_minutes, last_ping_time, toll_status, corridor_status,
            current_zone, distance_from_corridor_m, heartbeat_status, total_distance_km,
            fuel_remaining_liters, cumulative_fuel_burned, status
        ) VALUES (
            ?, ?, ?, ?, ?, ?, -25.76162, 28.53222, 0.0, 100, 1, 0, 0, ?, 'N4_CLEAR', 'CORRIDOR_COMPLIANT',
            'Pretoria East Depot (Dispatched - Awaiting Driver Activation)', 0.0, 'DISPATCHED', 0.0, ?, 0.0, 'AWAITING_ACTIVATION'
        );
        """, (driver_id, truck_reg.upper().strip(), driver_name.strip(), normalized_phone, clean_email, model, now_iso, fuel_liters))

        # Store pre-generated in-cab OTP code for instant on-screen display or email/direct login
        cursor.execute("""
        INSERT INTO driver_otps (phone_number, driver_email, otp_code, driver_id, truck_reg, created_at, expires_at, is_used)
        VALUES (?, ?, ?, ?, ?, ?, ?, 0);
        """, (normalized_phone, clean_email, raw_otp, driver_id, truck_reg.upper().strip(), now_iso, expires_at))

        conn.commit()
        conn.close()

        return {
            "driver_id": driver_id,
            "truck_reg": truck_reg.upper().strip(),
            "driver_name": driver_name.strip(),
            "driver_phone": normalized_phone,
            "driver_email": clean_email,
            "otp_code": formatted_otp,
            "raw_otp": raw_otp,
            "status": "AWAITING_ACTIVATION",
            "dispatched_at": now_iso
        }

    @staticmethod
    def request_driver_otp(phone_input: str) -> dict | None:
        import random
        import re
        from datetime import timedelta
        from .sms_service import sms_gateway

        clean_input = phone_input.strip()
        is_email = "@" in clean_input
        normalized_phone = ""
        digits_suffix = ""

        if not is_email:
            normalized_phone = sms_gateway.normalize_phone_number(clean_input)
            digits_suffix = re.sub(r"[^\d]", "", clean_input)[-9:]

        conn = get_connection()
        cursor = conn.cursor()

        # Look up pending or active unit matching this phone number or email
        if is_email:
            cursor.execute("""
            SELECT * FROM fleet_units 
            WHERE LOWER(driver_email) = LOWER(?)
            AND status IN ('AWAITING_ACTIVATION', 'ACTIVE', 'STANDBY')
            ORDER BY last_ping_time DESC LIMIT 1;
            """, (clean_input,))
        else:
            cursor.execute("""
            SELECT * FROM fleet_units 
            WHERE (driver_phone = ? OR driver_phone LIKE ?)
            AND status IN ('AWAITING_ACTIVATION', 'ACTIVE', 'STANDBY')
            ORDER BY last_ping_time DESC LIMIT 1;
            """, (normalized_phone, f"%{digits_suffix}"))

        unit_row = cursor.fetchone()

        if not unit_row:
            conn.close()
            return None

        unit = dict(unit_row)

        otp_num = random.randint(100000, 999999)
        raw_otp = str(otp_num)
        formatted_otp = f"{raw_otp[:3]}-{raw_otp[3:]}"

        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        expires_at = (now + timedelta(minutes=15)).isoformat()

        # Mark prior unused OTPs for this driver as used
        cursor.execute("UPDATE driver_otps SET is_used = 1 WHERE driver_id = ?;", (unit["driver_id"],))
        cursor.execute("""
        INSERT INTO driver_otps (phone_number, driver_email, otp_code, driver_id, truck_reg, created_at, expires_at, is_used)
        VALUES (?, ?, ?, ?, ?, ?, ?, 0);
        """, (unit.get("driver_phone", ""), unit.get("driver_email", ""), raw_otp, unit["driver_id"], unit["truck_reg"], now_iso, expires_at))

        conn.commit()
        conn.close()

        return {
            "driver_id": unit["driver_id"],
            "truck_reg": unit["truck_reg"],
            "driver_name": unit.get("driver_name", "Driver"),
            "phone_number": unit.get("driver_phone", "") or normalized_phone,
            "driver_email": unit.get("driver_email", ""),
            "otp_code": formatted_otp,
            "raw_otp": raw_otp,
            "expires_at": expires_at
        }

    @staticmethod
    def verify_driver_otp(phone_input: str, otp_code_input: str) -> dict | None:
        import re
        from .sms_service import sms_gateway

        clean_code = re.sub(r"[^\d]", "", otp_code_input.strip())
        now_iso = datetime.now(timezone.utc).isoformat()

        conn = get_connection()
        cursor = conn.cursor()

        clean_id = (phone_input or "").strip()
        is_email = "@" in clean_id

        otp_row = None
        if is_email:
            cursor.execute("""
            SELECT * FROM driver_otps
            WHERE LOWER(driver_email) = LOWER(?)
            AND otp_code = ?
            AND is_used = 0
            AND expires_at > ?
            ORDER BY created_at DESC LIMIT 1;
            """, (clean_id, clean_code, now_iso))
            otp_row = cursor.fetchone()
        elif clean_id:
            normalized_phone = sms_gateway.normalize_phone_number(clean_id)
            digits_suffix = re.sub(r"[^\d]", "", clean_id)[-9:]
            cursor.execute("""
            SELECT * FROM driver_otps
            WHERE (phone_number = ? OR phone_number LIKE ?)
            AND otp_code = ?
            AND is_used = 0
            AND expires_at > ?
            ORDER BY created_at DESC LIMIT 1;
            """, (normalized_phone, f"%{digits_suffix}", clean_code, now_iso))
            otp_row = cursor.fetchone()

        # Fallback 1: match by OTP code directly (allows direct 6-digit In-Cab code entry!)
        if not otp_row and clean_code:
            cursor.execute("""
            SELECT * FROM driver_otps
            WHERE otp_code = ?
            AND is_used = 0
            AND expires_at > ?
            ORDER BY created_at DESC LIMIT 1;
            """, (clean_code, now_iso))
            otp_row = cursor.fetchone()

        # Fallback 2: match pairing_tokens (PIN) if any
        if not otp_row and clean_code:
            cursor.execute("""
            SELECT * FROM pairing_tokens
            WHERE pin = ?
            AND is_used = 0
            AND expires_at > ?
            ORDER BY created_at DESC LIMIT 1;
            """, (clean_code, now_iso))
            token_row = cursor.fetchone()
            if token_row:
                tdata = dict(token_row)
                cursor.execute("UPDATE pairing_tokens SET is_used = 1 WHERE pin = ?;", (clean_code,))
                cursor.execute("""
                UPDATE fleet_units SET status = 'ACTIVE', heartbeat_status = 'ONLINE', last_ping_time = ? WHERE driver_id = ?;
                """, (now_iso, tdata["driver_id"]))
                cursor.execute("SELECT * FROM fleet_units WHERE driver_id = ?;", (tdata["driver_id"],))
                unit_row = cursor.fetchone()
                conn.commit()
                conn.close()
                return dict(unit_row) if unit_row else None

        if not otp_row:
            conn.close()
            return None

        otp_data = dict(otp_row)

        cursor.execute("UPDATE driver_otps SET is_used = 1 WHERE driver_id = ? AND otp_code = ?;", (otp_data["driver_id"], clean_code))
        cursor.execute("""
        UPDATE fleet_units
        SET status = 'ACTIVE', heartbeat_status = 'ONLINE'
        WHERE driver_id = ?;
        """, (otp_data["driver_id"],))

        cursor.execute("SELECT * FROM fleet_units WHERE driver_id = ?;", (otp_data["driver_id"],))
        unit_row = cursor.fetchone()
        conn.commit()
        conn.close()

        return dict(unit_row) if unit_row else None

    @staticmethod
    def purge_demo_units() -> int:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM fleet_units WHERE driver_id IN ('DRV-01', 'DRV-02', 'DRV-03', 'DRV-04', 'DRV-05', 'DRV-06', 'DRV-07') OR truck_reg LIKE '%WP 889 GP%' OR truck_reg LIKE '%KZN 782 GP%';")
        deleted = cursor.rowcount
        cursor.execute("DELETE FROM pairing_tokens;")
        cursor.execute("DELETE FROM driver_otps;")
        conn.commit()
        conn.close()
        return deleted

    @staticmethod
    def provision_new_unit(truck_reg: str, driver_name: str, phone: str = "", model: str = "Scania R500 V8", fuel_liters: float = 450.0) -> dict:
        import random
        from datetime import timedelta
        conn = get_connection()
        cursor = conn.cursor()

        # Generate next driver_id
        cursor.execute("SELECT driver_id FROM fleet_units WHERE driver_id LIKE 'DRV-%';")
        rows = cursor.fetchall()
        max_num = 0
        for r in rows:
            try:
                num = int(r["driver_id"].replace("DRV-", ""))
                if num > max_num:
                    max_num = num
            except Exception:
                pass
        driver_id = f"DRV-{str(max_num + 1).zfill(2)}"

        # Generate 6-digit PIN
        pin_num = random.randint(100000, 999999)
        raw_pin = str(pin_num)
        formatted_pin = f"{raw_pin[:3]}-{raw_pin[3:]}"

        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        expires_at = (now + timedelta(hours=24)).isoformat()

        # Insert pairing token
        cursor.execute("""
        INSERT INTO pairing_tokens (pin, driver_id, truck_reg, driver_name, driver_phone, created_at, expires_at, is_used)
        VALUES (?, ?, ?, ?, ?, ?, ?, 0);
        """, (raw_pin, driver_id, truck_reg, driver_name, phone, now_iso, expires_at))

        # Insert standby unit into fleet_units
        cursor.execute("""
        INSERT INTO fleet_units (
            driver_id, truck_reg, driver_name, model, lat, lng, speed_kmh, battery_pct, is_charging,
            continuous_drive_mins, idle_minutes, last_ping_time, toll_status, corridor_status,
            current_zone, distance_from_corridor_m, heartbeat_status, total_distance_km,
            fuel_remaining_liters, cumulative_fuel_burned, status
        ) VALUES (
            ?, ?, ?, ?, -25.76162, 28.53222, 0.0, 100, 1, 0, 0, ?, 'N4_CLEAR', 'CORRIDOR_COMPLIANT',
            'Depot Standby (Awaiting Driver Activation)', 0.0, 'STANDBY', 0.0, ?, 0.0, 'STANDBY'
        )
        ON CONFLICT(driver_id) DO UPDATE SET
            truck_reg = excluded.truck_reg,
            driver_name = excluded.driver_name,
            model = excluded.model,
            status = 'STANDBY',
            heartbeat_status = 'STANDBY';
        """, (driver_id, truck_reg, driver_name, model, now_iso, fuel_liters))

        conn.commit()
        conn.close()

        return {
            "driver_id": driver_id,
            "truck_reg": truck_reg,
            "driver_name": driver_name,
            "driver_phone": phone,
            "pin": formatted_pin,
            "raw_pin": raw_pin,
            "expires_at": expires_at,
            "status": "STANDBY"
        }

    @staticmethod
    def consume_pairing_pin(pin_input: str) -> dict | None:
        clean_pin = pin_input.replace("-", "").strip()
        now_iso = datetime.now(timezone.utc).isoformat()
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
        SELECT * FROM pairing_tokens 
        WHERE pin = ? AND is_used = 0 AND expires_at > ?;
        """, (clean_pin, now_iso))
        row = cursor.fetchone()

        if not row:
            conn.close()
            return None

        token_data = dict(row)

        # Mark token as used
        cursor.execute("UPDATE pairing_tokens SET is_used = 1 WHERE pin = ?;", (clean_pin,))
        # Activate unit
        cursor.execute("""
        UPDATE fleet_units 
        SET status = 'ACTIVE', heartbeat_status = 'ONLINE', last_ping_time = ? 
        WHERE driver_id = ?;
        """, (now_iso, token_data["driver_id"]))

        conn.commit()
        conn.close()

        return token_data

    @staticmethod
    def decommission_unit(driver_id: str, reason: str = "Driver Offboarded") -> bool:
        now_iso = datetime.now(timezone.utc).isoformat()
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM fleet_units WHERE driver_id = ?;", (driver_id,))
        unit = cursor.fetchone()
        if not unit:
            conn.close()
            return False

        truck_reg = unit["truck_reg"]
        driver_name = unit["driver_name"] or "Driver"

        cursor.execute("""
        UPDATE fleet_units 
        SET status = 'DECOMMISSIONED', heartbeat_status = 'REVOKED', last_ping_time = ? 
        WHERE driver_id = ?;
        """, (now_iso, driver_id))

        # Log decommissioning exception in audit ledger for SARS/RTMS records
        alert_id = f"alt-offboard-{driver_id}-{int(datetime.now(timezone.utc).timestamp())}"
        cursor.execute("""
        INSERT INTO alerts_log (
            alert_id, driver_id, truck_reg, type, severity, title, description,
            lat, lng, financial_impact_zar, created_at, status, resolved_at
        ) VALUES (
            ?, ?, ?, 'UNIT_DECOMMISSIONED', 'INFO', ?, ?,
            ?, ?, 0.0, ?, 'RESOLVED', ?
        );
        """, (
            alert_id, driver_id, truck_reg,
            f"🛡️ Unit Decommissioned: {truck_reg} ({driver_name})",
            f"Driver {driver_name} ({driver_id}) was offboarded from active corridor monitoring. Handset tracking revoked. Reason: {reason}",
            unit["lat"], unit["lng"], now_iso, now_iso
        ))

        # Invalidate any unused pairing tokens for this driver
        cursor.execute("UPDATE pairing_tokens SET is_used = 1 WHERE driver_id = ?;", (driver_id,))

        conn.commit()
        conn.close()
        return True

    @staticmethod
    def add_alert(alert: dict):
        conn = get_connection()
        conn.execute("""
        INSERT OR REPLACE INTO alerts_log (
            alert_id, driver_id, truck_reg, type, severity, title, description,
            lat, lng, financial_impact_zar, created_at, status, resolved_at
        ) VALUES (
            :alert_id, :driver_id, :truck_reg, :type, :severity, :title, :description,
            :lat, :lng, :financial_impact_zar, :created_at, :status, :resolved_at
        );
        """, alert)
        conn.commit()
        conn.close()

    @staticmethod
    def get_active_alerts(limit: int = 50) -> list[dict]:
        conn = get_connection()
        rows = conn.execute("SELECT * FROM alerts_log WHERE status = 'ACTIVE' ORDER BY created_at DESC LIMIT ?;", (limit,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    @staticmethod
    def get_all_alerts(limit: int = 100) -> list[dict]:
        conn = get_connection()
        rows = conn.execute("SELECT * FROM alerts_log ORDER BY created_at DESC LIMIT ?;", (limit,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    @staticmethod
    def resolve_alert(alert_id: str) -> bool:
        now_iso = datetime.now(timezone.utc).isoformat()
        conn = get_connection()
        cursor = conn.execute("UPDATE alerts_log SET status = 'RESOLVED', resolved_at = ? WHERE alert_id = ?;", (now_iso, alert_id))
        affected = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return affected
