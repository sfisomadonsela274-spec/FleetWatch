import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file if present
load_dotenv(Path(__file__).parent.parent / ".env")

class Config:
    PORT: int = int(os.getenv("PORT", 8001))
    HOST: str = os.getenv("HOST", "0.0.0.0")
    
    # Bearer Token Auth for Driver Mobile APK Ingress
    BEARER_TOKEN: str = os.getenv("FLEETSENTINEL_BEARER_TOKEN", "fleetsentinel_pilot_secret_token_2026")
    
    # ntfy.sh Push Relay
    NTFY_SERVER: str = os.getenv("NTFY_SERVER", "https://ntfy.sh")
    NTFY_TOPIC: str = os.getenv("NTFY_TOPIC", "fleetsentinel_n4_corridor_live")
    
    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./fleetsentinel.db")
    
    # APK Download Distribution URL (Dynamic for local dev vs production domain/CDN)
    APK_DOWNLOAD_BASE_URL: str = os.getenv("APK_DOWNLOAD_BASE_URL", "http://127.0.0.1:4000/download").rstrip("/")
    APK_DOWNLOAD_URL: str = os.getenv("APK_DOWNLOAD_URL", f"{APK_DOWNLOAD_BASE_URL}/FleetSentinel-Driver.apk")
    
    # Corridor & Rules Constants (N4 Highveld Corridor)
    CORRIDOR_BUFFER_METERS: float = 300.0
    FATIGUE_LIMIT_MINUTES: int = 240       # 4.0 hours RTMS ceiling
    FATIGUE_SPEED_THRESHOLD_KMH: float = 15.0
    PHONE_OFFLINE_THRESHOLD_SECONDS: int = 120  # 2 minutes cutoff
    EXCESSIVE_IDLE_MINUTES: int = 30       # 30 minutes outside waypoints
    EXCESSIVE_IDLE_RADIUS_METERS: float = 10.0
    
    # Fuel Model Baseline
    FUEL_BURN_RATE_L_PER_100KM: float = 34.0
    ROAD_TORTUOSITY_FACTOR: float = 1.22
    ZAR_DIESEL_PRICE_PER_LITER: float = 23.50

settings = Config()
