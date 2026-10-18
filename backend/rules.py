from datetime import datetime, timezone
import math
from .config import settings
from .geofences import (
    distance_to_corridor_meters,
    get_authorized_waypoint,
    check_toll_plaza,
    check_unauthorized_detour,
    haversine_distance
)

class ComplianceRulesEngine:
    """
    Evaluates telemetry pings against the 4 core FleetSentinel rules:
    - Rule 1: Corridor & Toll Skirting (300m N4 lateral buffer & off-ramp whitelisting)
    - Rule 2: Fatigue Rest Governor (240 mins continuous drive > 15 km/h)
    - Rule 3: Transit Phone Cutoff (> 120s without ping while speed > 0)
    - Rule 4: Excessive Idling (static < 10m at 0 km/h for > 30 mins outside waypoints)
    """

    @staticmethod
    def evaluate_ping(
        current_state: dict | None,
        driver_id: str,
        truck_reg: str,
        lat: float,
        lng: float,
        speed_kmh: float,
        battery_pct: int,
        is_charging: bool,
        ping_timestamp: datetime
    ) -> tuple[dict, list[dict]]:
        """
        Evaluates a new telemetry point and returns (updated_state, triggered_alerts).
        """
        triggered_alerts = []
        now_iso = ping_timestamp.isoformat()
        
        # Calculate time delta from previous ping if exists
        prev_ping_time = None
        elapsed_seconds = 30.0 # default assumption
        if current_state and current_state.get("last_ping_time"):
            try:
                prev_ping_time = datetime.fromisoformat(current_state["last_ping_time"])
                elapsed_seconds = max(1.0, (ping_timestamp - prev_ping_time).total_seconds())
            except Exception:
                pass

        # Calculate movement delta in meters from previous coordinates
        prev_lat = current_state.get("lat", lat) if current_state else lat
        prev_lng = current_state.get("lng", lng) if current_state else lng
        distance_moved_m = haversine_distance(prev_lat, prev_lng, lat, lng)

        current_ts = ping_timestamp.timestamp()
        prev_corridor_status = current_state.get("corridor_status") if current_state else None
        prev_toll_status = current_state.get("toll_status") if current_state else None
        last_corridor_alert_ts = current_state.get("last_corridor_alert_ts", 0) if current_state else 0
        last_toll_alert_ts = current_state.get("last_toll_alert_ts", 0) if current_state else 0
        last_fatigue_alert_ts = current_state.get("last_fatigue_alert_ts", 0) if current_state else 0
        last_cutoff_alert_ts = current_state.get("last_cutoff_alert_ts", 0) if current_state else 0
        last_battery_alert_ts = current_state.get("last_battery_alert_ts", 0) if current_state else 0

        # -------------------------------------------------------------
        # RULE 1: Corridor & Toll Skirting
        # -------------------------------------------------------------
        dist_to_corridor = distance_to_corridor_meters(lat, lng)
        authorized_wp = get_authorized_waypoint(lat, lng)
        toll_plaza = check_toll_plaza(lat, lng)
        unauthorized_detour = check_unauthorized_detour(lat, lng)

        corridor_status = "CORRIDOR_COMPLIANT"
        current_zone = "N4 Highveld Mainline"
        toll_status = "N4_CLEAR"

        if toll_plaza:
            toll_status = f"APPROACHING_{toll_plaza['id'].upper()}"
            current_zone = f"{toll_plaza['name']} Zone"

        if unauthorized_detour:
            corridor_status = "UNAUTHORIZED_DETOUR"
            current_zone = unauthorized_detour["name"]
            toll_status = "SANRAL_TOLL_BYPASS_ATTEMPT"
            if prev_toll_status != "SANRAL_TOLL_BYPASS_ATTEMPT" or (current_ts - last_toll_alert_ts >= 900):
                last_toll_alert_ts = current_ts
                triggered_alerts.append({
                    "alert_id": f"alt-detour-{driver_id}-{int(current_ts)}",
                    "driver_id": driver_id,
                    "truck_reg": truck_reg,
                    "type": "UNAUTHORIZED_TOLL_BYPASS",
                    "severity": "CRITICAL",
                    "title": f"🚨 Critical Toll Evasion Bypass: {unauthorized_detour['name']}",
                    "description": f"Truck {truck_reg} diverted onto gravel bypass {unauthorized_detour['name']} to evade Diamond Hill toll. Severe hijack risk alley.",
                    "lat": lat,
                    "lng": lng,
                    "financial_impact_zar": unauthorized_detour["risk_zar"],
                    "created_at": now_iso,
                    "status": "ACTIVE",
                    "resolved_at": None
                })
        elif authorized_wp:
            corridor_status = "AUTHORIZED_WAYPOINT"
            current_zone = authorized_wp["name"]
        elif dist_to_corridor <= settings.CORRIDOR_BUFFER_METERS:
            corridor_status = "CORRIDOR_COMPLIANT"
            current_zone = "N4 Highveld Corridor"
        else:
            corridor_status = "CORRIDOR_BREACH"
            current_zone = f"Off-Corridor ({round(dist_to_corridor)}m lateral breach)"
            if prev_corridor_status != "CORRIDOR_BREACH" or (current_ts - last_corridor_alert_ts >= 900):
                last_corridor_alert_ts = current_ts
                triggered_alerts.append({
                    "alert_id": f"alt-corridor-{driver_id}-{int(current_ts)}",
                    "driver_id": driver_id,
                    "truck_reg": truck_reg,
                    "type": "CORRIDOR_BREACH",
                    "severity": "HIGH",
                    "title": f"⚠️ Corridor Boundary Breach: {round(dist_to_corridor)}m from N4",
                    "description": f"Truck {truck_reg} departed the geofenced 300m N4 Highveld buffer at an unapproved location.",
                    "lat": lat,
                    "lng": lng,
                    "financial_impact_zar": 7500.0,
                    "created_at": now_iso,
                    "status": "ACTIVE",
                    "resolved_at": None
                })

        # -------------------------------------------------------------
        # RULE 2: Fatigue Rest Governor (240 mins continuous drive > 15 km/h)
        # -------------------------------------------------------------
        prev_continuous_mins = current_state.get("continuous_drive_mins", 0) if current_state else 0
        
        # If moving at transit speed, increment continuous driving minutes
        if speed_kmh >= settings.FATIGUE_SPEED_THRESHOLD_KMH:
            new_continuous_mins = prev_continuous_mins + max(1, round(elapsed_seconds / 60))
        elif authorized_wp and speed_kmh < 5.0 and elapsed_seconds >= 900: # 15 minutes rested at authorized stop
            new_continuous_mins = 0 # reset upon verified rest
        else:
            # stationary but not yet full 15 min rest: decay slightly
            new_continuous_mins = max(0, prev_continuous_mins - 1)

        if new_continuous_mins >= settings.FATIGUE_LIMIT_MINUTES:
            if prev_continuous_mins < settings.FATIGUE_LIMIT_MINUTES or (current_ts - last_fatigue_alert_ts >= 1800):
                last_fatigue_alert_ts = current_ts
                triggered_alerts.append({
                    "alert_id": f"alt-fatigue-{driver_id}-{int(current_ts)}",
                    "driver_id": driver_id,
                    "truck_reg": truck_reg,
                    "type": "FATIGUE_LIMIT_EXCEEDED",
                    "severity": "WARNING",
                    "title": f"🛑 RTMS Fatigue Limit Exceeded: {round(new_continuous_mins / 60, 1)}h Continuous Driving",
                    "description": f"Driver {driver_id} on {truck_reg} has exceeded the 4.0-hour statutory driving block without mandatory 15-minute rest.",
                    "lat": lat,
                    "lng": lng,
                    "financial_impact_zar": 3500.0,
                    "created_at": now_iso,
                    "status": "ACTIVE",
                    "resolved_at": None
                })

        # -------------------------------------------------------------
        # RULE 3: Transit Phone Cutoff (>120s gap while vehicle was in motion)
        # -------------------------------------------------------------
        prev_speed = current_state.get("speed_kmh", 0.0) if current_state else 0.0
        heartbeat_status = "ONLINE"
        
        if elapsed_seconds > settings.PHONE_OFFLINE_THRESHOLD_SECONDS and prev_speed > 0:
            heartbeat_status = "OFFLINE"
            if (current_ts - last_cutoff_alert_ts >= 900):
                last_cutoff_alert_ts = current_ts
                triggered_alerts.append({
                    "alert_id": f"alt-cutoff-{driver_id}-{int(current_ts)}",
                    "driver_id": driver_id,
                    "truck_reg": truck_reg,
                    "type": "PHONE_OFFLINE_IN_TRANSIT",
                    "severity": "HIGH",
                    "title": f"📡 Transit Telemetry Interrupted: {round(elapsed_seconds)}s Gap",
                    "description": f"Handset for truck {truck_reg} stopped transmitting while moving. Possible dead zone, power loss, or tamper.",
                    "lat": lat,
                    "lng": lng,
                    "financial_impact_zar": 2500.0,
                    "created_at": now_iso,
                    "status": "ACTIVE",
                    "resolved_at": None
                })
        elif battery_pct < 15 and not is_charging and speed_kmh > 15:
            heartbeat_status = "WARNING"
            if (current_ts - last_battery_alert_ts >= 1800):
                last_battery_alert_ts = current_ts
                triggered_alerts.append({
                    "alert_id": f"alt-battery-{driver_id}-{int(current_ts)}",
                    "driver_id": driver_id,
                    "truck_reg": truck_reg,
                    "type": "PHONE_CRITICAL_BATTERY",
                    "severity": "WARNING",
                    "title": f"🔋 Driver Phone Critical Battery: {battery_pct}% Unplugged",
                    "description": f"Driver handset on {truck_reg} is uncharged in transit on N4. Immediate tracking cutoff risk.",
                    "lat": lat,
                    "lng": lng,
                    "financial_impact_zar": 850.0,
                    "created_at": now_iso,
                    "status": "ACTIVE",
                    "resolved_at": None
                })

        # -------------------------------------------------------------
        # RULE 4: Excessive Idling (>30 mins static outside registered waypoints)
        # -------------------------------------------------------------
        prev_idle_mins = current_state.get("idle_minutes", 0) if current_state else 0
        new_idle_mins = 0

        # Stationary or negligible movement
        if speed_kmh == 0.0 and distance_moved_m <= settings.EXCESSIVE_IDLE_RADIUS_METERS:
            effective_elapsed = min(1800, elapsed_seconds)
            new_idle_mins = prev_idle_mins + max(1, round(effective_elapsed / 60))
        else:
            new_idle_mins = 0

        if new_idle_mins >= settings.EXCESSIVE_IDLE_MINUTES and not authorized_wp:
            should_alert = (prev_idle_mins < settings.EXCESSIVE_IDLE_MINUTES) or (new_idle_mins % 30 == 0)
            if should_alert:
                triggered_alerts.append({
                    "alert_id": f"alt-idle-{driver_id}-{int(current_ts)}",
                    "driver_id": driver_id,
                    "truck_reg": truck_reg,
                    "type": "EXCESSIVE_IDLE",
                    "severity": "WARNING",
                    "title": f"⏳ Excessive Idling Outside Waypoint: {new_idle_mins} Minutes",
                    "description": f"Truck {truck_reg} has been stationary for {new_idle_mins}m on an unapproved roadside section of N4.",
                    "lat": lat,
                    "lng": lng,
                    "financial_impact_zar": round((new_idle_mins / 60) * 3.5 * settings.ZAR_DIESEL_PRICE_PER_LITER), # ~3.5L/hr diesel idle burn
                    "created_at": now_iso,
                    "status": "ACTIVE",
                    "resolved_at": None
                })

        # Distance & Fuel Model Computations
        prev_distance_km = current_state.get("total_distance_km", 0.0) if current_state else 0.0
        km_increment = (distance_moved_m / 1000.0) * settings.ROAD_TORTUOSITY_FACTOR
        new_total_distance_km = round(prev_distance_km + km_increment, 2)

        prev_fuel = current_state.get("fuel_remaining_liters", 480.0) if current_state else 480.0
        fuel_burned_liters = (km_increment * settings.FUEL_BURN_RATE_L_PER_100KM) / 100.0
        new_fuel_remaining = max(10.0, round(prev_fuel - fuel_burned_liters, 1))

        # Build updated unit state
        updated_state = {
            "driver_id": driver_id,
            "truck_reg": truck_reg,
            "driver_name": current_state.get("driver_name", "Sipho Zulu") if current_state else "Driver " + driver_id,
            "model": current_state.get("model", "Scania R500 V8") if current_state else "Heavy Freight Unit",
            "lat": lat,
            "lng": lng,
            "speed_kmh": speed_kmh,
            "battery_pct": battery_pct,
            "is_charging": 1 if is_charging else 0,
            "continuous_drive_mins": new_continuous_mins,
            "idle_minutes": new_idle_mins,
            "last_ping_time": now_iso,
            "toll_status": toll_status,
            "corridor_status": corridor_status,
            "current_zone": current_zone,
            "distance_from_corridor_m": round(dist_to_corridor, 1),
            "heartbeat_status": heartbeat_status,
            "status": "ACTIVE",
            "total_distance_km": new_total_distance_km,
            "fuel_remaining_liters": new_fuel_remaining,
            "cumulative_fuel_burned": round((current_state.get("cumulative_fuel_burned", 0.0) if current_state else 0.0) + fuel_burned_liters, 2),
            "last_corridor_alert_ts": last_corridor_alert_ts,
            "last_toll_alert_ts": last_toll_alert_ts,
            "last_fatigue_alert_ts": last_fatigue_alert_ts,
            "last_cutoff_alert_ts": last_cutoff_alert_ts,
            "last_battery_alert_ts": last_battery_alert_ts
        }

        return updated_state, triggered_alerts

rules_engine = ComplianceRulesEngine()
