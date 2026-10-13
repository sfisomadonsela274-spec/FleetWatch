import json
import math
import os
from pathlib import Path
from shapely.geometry import Point, Polygon, LineString

CURRENT_DIR = Path(__file__).parent
COORDS_FILE = CURRENT_DIR / "geofence_coords.json"

# South African Highveld metric projection constants (around -25.8 deg S, 28.5 deg E)
REF_LAT = -25.8
REF_LON = 28.5
METERS_PER_LAT_DEG = 110800.0
METERS_PER_LON_DEG = 111320.0 * math.cos(math.radians(REF_LAT)) # approx 100225.4 m/deg

def to_metric(lon: float, lat: float) -> tuple[float, float]:
    """Converts WGS84 (lon, lat) to local Cartesian metric meters."""
    x = (lon - REF_LON) * METERS_PER_LON_DEG
    y = (lat - REF_LAT) * METERS_PER_LAT_DEG
    return (x, y)

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Computes Great-Circle distance in meters."""
    R = 6371000.0  # Earth radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2.0)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0)**2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c

# Load N4 Route Coordinates
with open(COORDS_FILE, "r") as f:
    RAW_N4_COORDS = json.load(f)  # [[lon, lat], ...]

# Metric LineString for sub-meter distance
N4_METRIC_COORDS = [to_metric(lon, lat) for lon, lat in RAW_N4_COORDS]
N4_METRIC_LINE = LineString(N4_METRIC_COORDS)
N4_GEO_LINE = LineString(RAW_N4_COORDS)

# Authorized Waypoint Polygons
AUTHORIZED_WAYPOINTS = [
    {
        "id": "exc-pta-depot",
        "name": "Pretoria East Depot & Silver Lakes Departure Hub",
        "polygon": Polygon([
            [28.3100, -25.7400],
            [28.3300, -25.7400],
            [28.3300, -25.7600],
            [28.3100, -25.7600],
            [28.3100, -25.7400]
        ]),
        "max_dwell_minutes": 60,
        "type": "DEPOT"
    },
    {
        "id": "exc-rayton-truckstop",
        "name": "Rayton R515 Off-Ramp & Petroport Truck Stop",
        "polygon": Polygon([
            [28.5200, -25.7550],
            [28.5450, -25.7550],
            [28.5450, -25.7720],
            [28.5200, -25.7720],
            [28.5200, -25.7550]
        ]),
        "max_dwell_minutes": 45,
        "type": "REFUEL_REST"
    },
    {
        "id": "exc-clewer-layby",
        "name": "Clewer Mining Depot & Rest Lay-By",
        "polygon": Polygon([
            [29.0900, -25.8550],
            [29.1150, -25.8550],
            [29.1150, -25.8700],
            [29.0900, -25.8700],
            [29.0900, -25.8550]
        ]),
        "max_dwell_minutes": 60,
        "type": "WEIGHBRIDGE_REST"
    },
    {
        "id": "exc-witbank-terminal",
        "name": "Witbank Central Freight Terminal & Coal Hub",
        "polygon": Polygon([
            [29.2100, -25.8650],
            [29.2450, -25.8650],
            [29.2450, -25.8850],
            [29.2100, -25.8850],
            [29.2100, -25.8650]
        ]),
        "max_dwell_minutes": 120,
        "type": "TERMINAL"
    }
]

# Known Toll Plazas
TOLL_PLAZAS = [
    {
        "id": "toll-diamond-hill",
        "name": "Diamond Hill Toll Plaza (SANRAL)",
        "center": (28.5991, -25.8082), # (lon, lat)
        "radius_meters": 400.0,
        "class3_zar": 182.00
    },
    {
        "id": "toll-middelburg",
        "name": "Middelburg Toll Plaza (SANRAL)",
        "center": (29.5442, -25.7954),
        "radius_meters": 400.0,
        "class3_zar": 154.00
    }
]

# Unauthorized Detour & Hijack Hotspots (Balmoral R104 Dirt Bypass)
UNAUTHORIZED_DETOURS = [
    {
        "id": "detour-r104-balmoral",
        "name": "R104 Balmoral Dirt Bypass (Toll Evasion & Hijack Hotspot)",
        "center": (28.8950, -25.8350), # (lon, lat)
        "radius_meters": 800.0,
        "risk_zar": 17500.0
    }
]

def distance_to_corridor_meters(lat: float, lng: float) -> float:
    """Calculates distance in meters from given point to the N4 centerline."""
    pt_metric = Point(to_metric(lng, lat))
    return float(N4_METRIC_LINE.distance(pt_metric))

def get_authorized_waypoint(lat: float, lng: float) -> dict | None:
    """Checks if the point falls inside any authorized waypoint polygon."""
    pt = Point(lng, lat)
    for wp in AUTHORIZED_WAYPOINTS:
        if wp["polygon"].contains(pt):
            return wp
    return None

def check_toll_plaza(lat: float, lng: float) -> dict | None:
    """Checks if the vehicle is approaching or inside a SANRAL toll plaza."""
    for tp in TOLL_PLAZAS:
        dist = haversine_distance(lat, lng, tp["center"][1], tp["center"][0])
        if dist <= tp["radius_meters"]:
            return {**tp, "distance_meters": dist}
    return None

def check_unauthorized_detour(lat: float, lng: float) -> dict | None:
    """Checks if the vehicle diverted into a known high-risk toll evasion detour."""
    for det in UNAUTHORIZED_DETOURS:
        dist = haversine_distance(lat, lng, det["center"][1], det["center"][0])
        if dist <= det["radius_meters"]:
            return {**det, "distance_meters": dist}
    return None
