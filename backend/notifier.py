import httpx
import logging
from .config import settings

logger = logging.getLogger("fleetsentinel.notifier")

PRIORITY_MAP = {
    "CRITICAL": "5",   # urgent (popup + persistent sound)
    "HIGH": "4",       # high
    "WARNING": "3",    # default
    "INFO": "2"        # low
}

TAGS_MAP = {
    "CORRIDOR_BREACH": "rotating_light,triangular_flag_on_post",
    "UNAUTHORIZED_TOLL_BYPASS": "skull_and_crossbones,warning",
    "FATIGUE_LIMIT_EXCEEDED": "stopwatch,sleeping_bed",
    "PHONE_OFFLINE_IN_TRANSIT": "signal_strength,battery",
    "EXCESSIVE_IDLE": "hourglass,fuelpump",
    "SPEEDING_VIOLATION": "zap,tachometer"
}

async def dispatch_ntfy_alert(alert: dict) -> bool:
    """
    Dispatches exception notification to ntfy.sh topic.
    Receivers on desktop (browser or desktop app) get instant push notifications.
    """
    url = f"{settings.NTFY_SERVER.rstrip('/')}/{settings.NTFY_TOPIC}"
    priority = PRIORITY_MAP.get(alert.get("severity", "WARNING"), "3")
    tags = TAGS_MAP.get(alert.get("type", ""), "warning,truck")
    
    # Sanitize title for HTTP header (headers must be ASCII)
    raw_title = alert.get("title", "FleetSentinel Compliance Exception")
    clean_title = raw_title.encode("ascii", "ignore").decode("ascii").strip()
    if not clean_title:
        clean_title = f"FleetSentinel Exception: {alert.get('type', 'ALERT')}"
    
    headers = {
        "Title": clean_title,
        "Priority": priority,
        "Tags": tags,
        "X-Click": f"http://localhost:4000/?view=dashboard#alert-{alert.get('alert_id', '')}"
    }
    
    # Financial penalty badge in body if available
    body = alert.get("description", "")
    fin_impact = alert.get("financial_impact_zar", 0)
    if fin_impact and fin_impact > 0:
        body += f"\n💰 Financial Risk: R{fin_impact:,.2f}"
        
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.post(url, content=body.encode("utf-8"), headers=headers)
            if resp.status_code == 200:
                logger.info(f"[ntfy.sh] Alert dispatched: {alert.get('title')} to {url}")
                return True
            else:
                logger.warning(f"[ntfy.sh] Unexpected status {resp.status_code}: {resp.text}")
                return False
    except Exception as e:
        logger.warning(f"[ntfy.sh] Notice: Push dispatch bypassed ({type(e).__name__}): {e or 'network timeout'}")
        return False
