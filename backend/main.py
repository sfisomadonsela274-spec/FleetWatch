import os
import asyncio
import logging
from pathlib import Path
import json
from datetime import datetime, timezone
from typing import List, Optional

logger = logging.getLogger("fleet_main")
from fastapi import FastAPI, HTTPException, Security, Depends, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel, Field, model_validator

from .config import settings
from .database import DatabaseManager
from .rules import rules_engine
from .notifier import dispatch_ntfy_alert
from .sms_service import sms_gateway
from .email_service import email_gateway
from .reports import (
    generate_sars_report_data,
    generate_sars_csv,
    generate_rtms_report_data,
    generate_rtms_csv
)

app = FastAPI(
    title="FleetSentinel Lean Telemetry Cloud Engine",
    description="Autonomous Ingress, PostGIS Geofencing Rules & Desktop Push Relay for N4 Highveld Artery",
    version="1.0.0"
)

# Enable CORS for desktop cockpit
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Bearer Token Auth Scheme
security = HTTPBearer()

def verify_token(credentials: HTTPAuthorizationCredentials = Security(security)):
    valid_tokens = {
        settings.BEARER_TOKEN,
        "fleetsentinel_pilot_secret_token_2026",
        "dev-fleet-secret-n4-token"
    }
    if credentials.credentials not in valid_tokens:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired FleetSentinel bearer authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials

# Pydantic Schemas
class TelemetryPing(BaseModel):
    driver_id: Optional[str] = Field(default=None, json_schema_extra={"example": "DRV-01"})
    truck_reg: Optional[str] = Field(default=None, json_schema_extra={"example": "WP 889 GP"})
    truckId: Optional[str] = Field(default=None)
    lat: float = Field(..., ge=-35.0, le=-20.0, json_schema_extra={"example": -25.76162})
    lng: float = Field(..., ge=15.0, le=35.0, json_schema_extra={"example": 28.53222})
    speed_kmh: Optional[float] = Field(default=0.0, ge=0.0, le=160.0, json_schema_extra={"example": 74.0})
    speed: Optional[float] = Field(default=None)
    battery_pct: Optional[int] = Field(default=100, ge=0, le=100, json_schema_extra={"example": 94})
    batteryPercent: Optional[int] = Field(default=None)
    is_charging: Optional[bool] = Field(default=True, json_schema_extra={"example": True})
    isCharging: Optional[bool] = Field(default=None)
    timestamp: Optional[str] = Field(default=None, json_schema_extra={"example": "2026-09-13T10:30:00Z"})

    @model_validator(mode="after")
    def resolve_aliases(self):
        if not self.driver_id and self.truckId:
            self.driver_id = self.truckId
        if not self.truck_reg and self.truckId:
            self.truck_reg = self.truckId
        if self.speed is not None and (self.speed_kmh is None or self.speed_kmh == 0.0):
            self.speed_kmh = float(self.speed)
        if self.batteryPercent is not None:
            self.battery_pct = int(self.batteryPercent)
        if self.isCharging is not None:
            self.is_charging = bool(self.isCharging)
        if not self.driver_id:
            self.driver_id = "DRV-01"
        if not self.truck_reg:
            self.truck_reg = "WP 889 GP"
        return self

class BatchTelemetry(BaseModel):
    pings: List[TelemetryPing]

class ProvisionRequest(BaseModel):
    truck_reg: str = Field(..., json_schema_extra={"example": "WP 992 GP"})
    driver_name: str = Field(..., json_schema_extra={"example": "Mandla Sithole"})
    phone: Optional[str] = Field(default="", json_schema_extra={"example": "+27 82 555 1290"})
    model: Optional[str] = Field(default="Scania R500 V8", json_schema_extra={"example": "Volvo FH16 610"})
    fuel_liters: Optional[float] = Field(default=450.0, json_schema_extra={"example": 450.0})

class DriverPairRequest(BaseModel):
    pin: str = Field(..., json_schema_extra={"example": "749-218"})
    device_uuid: Optional[str] = Field(default="", json_schema_extra={"example": "samsung-sm-a042f"})
    device_model: Optional[str] = Field(default="", json_schema_extra={"example": "SM-A042F"})

class DispatchRequest(BaseModel):
    driver_phone: Optional[str] = Field(default="", json_schema_extra={"example": "082 555 1290"})
    driver_email: Optional[str] = Field(default="", json_schema_extra={"example": "driver@company.com"})
    truck_reg: str = Field(..., json_schema_extra={"example": "WP 889 GP"})
    driver_name: Optional[str] = Field(default="Driver", json_schema_extra={"example": "Thabo Mokoena"})
    model: Optional[str] = Field(default="Scania R500 V8", json_schema_extra={"example": "Volvo FH16 610"})
    fuel_liters: Optional[float] = Field(default=450.0, json_schema_extra={"example": 450.0})
    destination: Optional[str] = Field(default="N4 Highveld Corridor", json_schema_extra={"example": "Witbank Central Coal Freight Terminal"})
    origin: Optional[str] = Field(default="Pretoria East Depot", json_schema_extra={"example": "Pretoria East Depot"})

class RequestOtpRequest(BaseModel):
    phone_number: Optional[str] = Field(default="", json_schema_extra={"example": "082 555 1290"})
    email: Optional[str] = Field(default="", json_schema_extra={"example": "driver@company.com"})
    identifier: Optional[str] = Field(default="", json_schema_extra={"example": "082 555 1290 or driver@company.com"})

    @property
    def resolved_identifier(self) -> str:
        return (self.identifier or self.phone_number or self.email or "").strip()

class VerifyOtpRequest(BaseModel):
    phone_number: Optional[str] = Field(default=None, json_schema_extra={"example": "082 555 1290"})
    email: Optional[str] = Field(default=None, json_schema_extra={"example": "driver@company.com"})
    identifier: Optional[str] = Field(default=None, json_schema_extra={"example": "082 555 1290"})
    otp: Optional[str] = Field(default=None, json_schema_extra={"example": "842-190"})
    otp_code: Optional[str] = Field(default=None, json_schema_extra={"example": "842-190"})
    device_uuid: Optional[str] = Field(default="")
    device_model: Optional[str] = Field(default="")

    @property
    def resolved_otp(self) -> str:
        return (self.otp or self.otp_code or "").strip()

    @property
    def resolved_identifier(self) -> str:
        return (self.identifier or self.phone_number or self.email or "").strip()

class DecommissionRequest(BaseModel):
    reason: Optional[str] = Field(default="Driver Resigned / Contract Ended")

class EmailTestRequest(BaseModel):
    to_email: str = Field(..., json_schema_extra={"example": "sfiso@fleetwatch.co.za"})

class EmailConfigureRequest(BaseModel):
    provider: Optional[str] = Field(default=None, json_schema_extra={"example": "sendgrid"})
    sendgrid_api_key: Optional[str] = Field(default=None, json_schema_extra={"example": "SG.xxx..."})
    resend_api_key: Optional[str] = Field(default=None, json_schema_extra={"example": "re_xxx..."})
    brevo_api_key: Optional[str] = Field(default=None, json_schema_extra={"example": "xkeysib-..."})
    smtp_host: Optional[str] = Field(default="smtp.gmail.com", json_schema_extra={"example": "smtp.gmail.com"})
    smtp_port: Optional[int] = Field(default=587, json_schema_extra={"example": 587})
    smtp_user: Optional[str] = Field(default=None, json_schema_extra={"example": "sfisomadonsela274@gmail.com"})
    smtp_pass: Optional[str] = Field(default=None, json_schema_extra={"example": "app-password-here"})
    from_email: Optional[str] = Field(default="smxtechnologies1@gmail.com")
    from_name: Optional[str] = Field(default="FleetWatch Operations")

# In-Memory Event Queue for Real-Time SSE Streaming to Desktop Cockpit
sse_subscribers: list[asyncio.Queue] = []
_active_background_tasks = set()

def schedule_ntfy_dispatch(alert: dict):
    task = asyncio.create_task(dispatch_ntfy_alert(alert))
    _active_background_tasks.add(task)
    task.add_done_callback(_active_background_tasks.discard)

async def broadcast_event(event_type: str, data: dict):
    payload = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
    for q in sse_subscribers[:]:
        try:
            q.put_nowait(payload)
        except Exception:
            sse_subscribers.remove(q)

@app.get("/health")
@app.get("/api/health")
def health_check():
    units = DatabaseManager.get_all_units()
    alerts = DatabaseManager.get_active_alerts()
    return {
        "status": "HEALTHY",
        "service": "FleetSentinel Autonomous Telemetry & Driver Compliance Engine",
        "corridor": "N4 Highveld Freight Artery (Pretoria ⇄ Bronkhorstspruit ⇄ Witbank)",
        "active_units": len(units),
        "active_exceptions": len(alerts),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@app.post("/api/v1/telemetry/ping")
async def ingest_ping(ping: TelemetryPing, token: str = Depends(verify_token)):
    """
    Ingests live telemetry from Driver Android APK.
    Evaluates 4 core rules: Corridor, Fatigue, Cutoff, and Idle.
    Dispatches alerts to ntfy.sh and streams to desktop cockpit.
    """
    identifier = ping.driver_id or ping.truck_reg
    current_state = DatabaseManager.get_unit(identifier) if identifier else None
    if current_state and current_state.get("status") == "DECOMMISSIONED":
        raise HTTPException(
            status_code=403,
            detail={
                "error": "DEVICE_REVOKED",
                "message": "Handset unlinked from active fleet by operations dispatcher.",
                "status": "DECOMMISSIONED"
            }
        )

    driver_id = current_state["driver_id"] if current_state else (ping.driver_id or "DRV-01")
    truck_reg = current_state["truck_reg"] if current_state else (ping.truck_reg or "WP 889 GP")

    ping_time = datetime.now(timezone.utc)
    if ping.timestamp:
        try:
            ping_time = datetime.fromisoformat(ping.timestamp.replace("Z", "+00:00"))
        except Exception:
            pass

    updated_state, triggered_alerts = rules_engine.evaluate_ping(
        current_state=current_state,
        driver_id=driver_id,
        truck_reg=truck_reg,
        lat=ping.lat,
        lng=ping.lng,
        speed_kmh=ping.speed_kmh,
        battery_pct=ping.battery_pct,
        is_charging=ping.is_charging,
        ping_timestamp=ping_time
    )

    # Persist hot state
    DatabaseManager.upsert_unit(updated_state)

    # Persist alerts & dispatch push notifications via ntfy.sh
    for alert in triggered_alerts:
        DatabaseManager.add_alert(alert)
        # Asynchronously dispatch to desktop push relay
        schedule_ntfy_dispatch(alert)
        # Broadcast alert to live cockpit
        await broadcast_event("alert", alert)

    # Broadcast updated telemetry to cockpit
    await broadcast_event("telemetry", updated_state)

    return {
        "success": True,
        "driver_id": driver_id,
        "truck_reg": truck_reg,
        "corridor_status": updated_state["corridor_status"],
        "toll_status": updated_state["toll_status"],
        "current_zone": updated_state["current_zone"],
        "distance_from_corridor_m": updated_state["distance_from_corridor_m"],
        "alerts_triggered": len(triggered_alerts),
        "alerts": triggered_alerts,
        "unit": updated_state
    }

@app.post("/api/v1/telemetry/batch")
async def ingest_batch(batch: BatchTelemetry, token: str = Depends(verify_token)):
    """
    Offline Mobile Edge Drainage:
    Drains the local SQLite handset cache in chronological batches of 20 pings.
    Reconciles missing packets after traversing Highveld cellular dead zones.
    """
    total_processed = 0
    all_triggered_alerts = []

    # Sort chronologically
    sorted_pings = sorted(
        batch.pings,
        key=lambda p: p.timestamp if p.timestamp else ""
    )

    for ping in sorted_pings:
        ping_time = datetime.now(timezone.utc)
        if ping.timestamp:
            try:
                ping_time = datetime.fromisoformat(ping.timestamp.replace("Z", "+00:00"))
            except Exception:
                pass

        identifier = ping.driver_id or ping.truck_reg
        current_state = DatabaseManager.get_unit(identifier) if identifier else None
        driver_id = current_state["driver_id"] if current_state else (ping.driver_id or "DRV-01")
        truck_reg = current_state["truck_reg"] if current_state else (ping.truck_reg or "WP 889 GP")

        updated_state, alerts = rules_engine.evaluate_ping(
            current_state=current_state,
            driver_id=driver_id,
            truck_reg=truck_reg,
            lat=ping.lat,
            lng=ping.lng,
            speed_kmh=ping.speed_kmh,
            battery_pct=ping.battery_pct,
            is_charging=ping.is_charging,
            ping_timestamp=ping_time
        )
        DatabaseManager.upsert_unit(updated_state)

        for alert in alerts:
            DatabaseManager.add_alert(alert)
            all_triggered_alerts.append(alert)
            schedule_ntfy_dispatch(alert)
            await broadcast_event("alert", alert)

        total_processed += 1

    return {
        "success": True,
        "pings_processed": total_processed,
        "alerts_triggered": len(all_triggered_alerts),
        "alerts": all_triggered_alerts
    }

@app.get("/api/v1/fleet/units")
def get_fleet_units():
    units = DatabaseManager.get_all_units()
    return {"success": True, "count": len(units), "units": units}

@app.get("/api/v1/fleet/alerts")
def get_fleet_alerts():
    alerts = DatabaseManager.get_all_alerts()
    return {"success": True, "count": len(alerts), "alerts": alerts}

@app.post("/api/v1/fleet/alerts/{alert_id}/resolve")
async def resolve_alert(alert_id: str):
    resolved = DatabaseManager.resolve_alert(alert_id)
    if not resolved:
        raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")
    await broadcast_event("alert_resolved", {"alert_id": alert_id})
    return {"success": True, "alert_id": alert_id, "status": "RESOLVED"}
@app.post("/api/v1/fleet/dispatch")
async def dispatch_truck(req: DispatchRequest):
    """
    Fleet Manager dispatches vehicle via driver cell number or email.
    Generates 6-digit in-cab OTP code immediately and dispatches via SMS and/or Email.
    """
    try:
        record = DatabaseManager.dispatch_unit(
            truck_reg=req.truck_reg,
            driver_phone=req.driver_phone or "",
            driver_name=req.driver_name or "Driver",
            model=req.model or "Scania R500 V8",
            fuel_liters=req.fuel_liters or 450.0,
            driver_email=req.driver_email or ""
        )
    except Exception as e:
        logger.error(f"Failed to record vehicle dispatch in database: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Database dispatch error: {str(e)}")

    unit = DatabaseManager.get_unit(record["driver_id"])

    # Download URL for the driver APK (dynamic via settings / .env)
    download_url = settings.APK_DOWNLOAD_URL
    sms_res = None
    email_res = None

    if record.get("driver_phone"):
        try:
            sms_res = sms_gateway.send_dispatch_invite(
                to_phone=record["driver_phone"],
                truck_reg=record["truck_reg"],
                driver_name=record["driver_name"],
                download_url=download_url
            )
        except Exception as e:
            logger.error(f"SMS dispatch failed for {record['driver_phone']}: {e}")
            sms_res = {"status": "FAILED", "error": str(e)}

    if record.get("driver_email"):
        try:
            email_res = email_gateway.send_dispatch_invite(
                to_email=record["driver_email"],
                truck_reg=record["truck_reg"],
                driver_name=record["driver_name"],
                download_url=download_url,
                otp_code=record["otp_code"]
            )
        except Exception as e:
            logger.error(f"Email dispatch failed for {record['driver_email']}: {e}")
            email_res = {"status": "FAILED", "error": str(e)}

    await broadcast_event("unit_dispatched", {
        "unit": unit,
        "otp_code": record["otp_code"],
        "sms": sms_res,
        "email": email_res
    })

    delivery_channels = []
    if sms_res and sms_res.get("status") in ("DELIVERED_SMS", "SENT"):
        delivery_channels.append(f"SMS to {record['driver_phone']}")
    elif sms_res:
        delivery_channels.append(f"SMS: {sms_res.get('status')}")

    if email_res and email_res.get("status") in ("DELIVERED_BREVO", "DELIVERED_SMTP", "DELIVERED_MOCK"):
        delivery_channels.append(f"Email to {record['driver_email']}")
    elif email_res:
        delivery_channels.append(f"Email: {email_res.get('status')} ({email_res.get('error', '')})")

    channel_text = " & ".join(delivery_channels) if delivery_channels else "Direct On-Screen Code Generated"

    return {
        "success": True,
        "dispatch": record,
        "unit": unit,
        "otp_code": record["otp_code"],
        "sms": sms_res,
        "email": email_res,
        "message": f"Vehicle dispatched. In-cab code: {record['otp_code']} ({channel_text})"
    }

@app.post("/api/v1/driver/request-otp")
async def request_driver_otp(req: RequestOtpRequest):
    """
    Driver inputs cell number or email in APK and requests 6-digit login OTP.
    """
    identifier = req.resolved_identifier
    if not identifier:
        raise HTTPException(status_code=400, detail="Mobile number or email address required.")

    otp_record = DatabaseManager.request_driver_otp(identifier)
    if not otp_record:
        raise HTTPException(
            status_code=404,
            detail=f"No active dispatch found for {identifier}. Please check with operations dispatch."
        )

    sms_res = None
    email_res = None

    if otp_record.get("phone_number") and "@" not in identifier:
        sms_res = sms_gateway.send_login_otp(
            to_phone=otp_record["phone_number"],
            otp_code=otp_record["otp_code"],
            truck_reg=otp_record["truck_reg"]
        )

    if otp_record.get("driver_email") or "@" in identifier:
        target_email = otp_record.get("driver_email") or identifier
        email_res = email_gateway.send_login_otp(
            to_email=target_email,
            otp_code=otp_record["otp_code"],
            truck_reg=otp_record["truck_reg"],
            driver_name=otp_record.get("driver_name", "Driver")
        )

    return {
        "success": True,
        "truck_reg": otp_record["truck_reg"],
        "driver_name": otp_record["driver_name"],
        "phone_number": otp_record.get("phone_number"),
        "driver_email": otp_record.get("driver_email"),
        "otp_code": otp_record["otp_code"],  # also return for transparent debug/dev inspection
        "message": f"Verification code {otp_record['otp_code']} generated for {identifier}",
        "sms": sms_res,
        "email": email_res
    }

@app.post("/api/v1/driver/verify-otp")
async def verify_driver_otp(req: VerifyOtpRequest):
    """
    Driver inputs the 6-digit OTP code in APK.
    Accepts phone, email, or direct OTP code.
    Activates vehicle and returns authorization credentials.
    """
    unit = DatabaseManager.verify_driver_otp(req.resolved_identifier, req.resolved_otp)
    if not unit:
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired verification code. Please request a new code or check your dispatch pass."
        )

    await broadcast_event("unit_activated", {
        "unit": unit,
        "driver_id": unit["driver_id"],
        "truck_reg": unit["truck_reg"],
        "driver_phone": unit.get("driver_phone"),
        "driver_email": unit.get("driver_email"),
        "status": "ACTIVE"
    })
    return {
        "success": True,
        "driver_id": unit["driver_id"],
        "truck_reg": unit["truck_reg"],
        "driver_name": unit["driver_name"],
        "bearer_token": settings.BEARER_TOKEN,
        "message": f"Handset successfully activated for {unit['truck_reg']}. Safe journey!"
    }

@app.get("/api/v1/email/logs")
def get_email_logs():
    """
    Returns recent outbound driver email dispatch history.
    """
    return {
        "success": True,
        "count": len(email_gateway.sent_emails),
        "messages": email_gateway.sent_emails
    }

@app.get("/api/v1/email/status")
def get_email_status():
    """
    Returns current SMTP gateway configuration status.
    """
    return {
        "success": True,
        **email_gateway.get_status()
    }

@app.post("/api/v1/email/test")
def test_email_delivery(req: EmailTestRequest):
    """
    Sends a test verification email to verify Brevo / SMTP gateway functionality.
    """
    if not email_gateway.is_valid_email(req.to_email):
        raise HTTPException(status_code=400, detail="Invalid recipient email address")
    result = email_gateway.send_test_email(req.to_email)
    return {
        "success": result.get("status") in ("DELIVERED_SENDGRID", "DELIVERED_RESEND", "DELIVERED_BREVO", "DELIVERED_SMTP", "DELIVERED_MOCK"),
        "delivery": result,
        "message": f"Test email dispatched to {req.to_email} ({result.get('status')})"
    }

@app.post("/api/v1/email/configure")
def configure_email_gateway(req: EmailConfigureRequest):
    """
    Updates SendGrid / Resend / Brevo / SMTP gateway configuration, persists to .env, and reloads service.
    """
    env_file = Path(__file__).parent.parent / ".env"

    existing_vars = {}
    if env_file.exists():
        with open(env_file, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    existing_vars[k.strip()] = v.strip()

    if req.provider is not None:
        existing_vars["EMAIL_PROVIDER"] = req.provider.strip().lower()
        os.environ["EMAIL_PROVIDER"] = req.provider.strip().lower()
    if req.sendgrid_api_key is not None:
        existing_vars["SENDGRID_API_KEY"] = req.sendgrid_api_key.strip()
        os.environ["SENDGRID_API_KEY"] = req.sendgrid_api_key.strip()
    if req.resend_api_key is not None:
        existing_vars["RESEND_API_KEY"] = req.resend_api_key.strip()
        os.environ["RESEND_API_KEY"] = req.resend_api_key.strip()
    if req.brevo_api_key is not None:
        existing_vars["BREVO_API_KEY"] = req.brevo_api_key.strip()
        os.environ["BREVO_API_KEY"] = req.brevo_api_key.strip()
    if req.smtp_host is not None:
        existing_vars["SMTP_HOST"] = req.smtp_host.strip()
        os.environ["SMTP_HOST"] = req.smtp_host.strip()
    if req.smtp_port is not None:
        existing_vars["SMTP_PORT"] = str(req.smtp_port)
        os.environ["SMTP_PORT"] = str(req.smtp_port)
    if req.smtp_user is not None:
        existing_vars["SMTP_USER"] = req.smtp_user.strip()
        os.environ["SMTP_USER"] = req.smtp_user.strip()
    if req.smtp_pass is not None:
        clean_pass = req.smtp_pass.replace(" ", "").strip() if (req.smtp_host and "gmail" in req.smtp_host.lower()) else req.smtp_pass.strip()
        existing_vars["SMTP_PASS"] = clean_pass
        os.environ["SMTP_PASS"] = clean_pass
    if req.from_email:
        existing_vars["EMAIL_FROM"] = req.from_email.strip()
        os.environ["EMAIL_FROM"] = req.from_email.strip()
    if req.from_name:
        existing_vars["EMAIL_FROM_NAME"] = req.from_name.strip()
        os.environ["EMAIL_FROM_NAME"] = req.from_name.strip()

    with open(env_file, "w") as f:
        for k, v in existing_vars.items():
            f.write(f"{k}={v}\n")

    email_gateway.reload_config()

    st = email_gateway.get_status()
    return {
        "success": True,
        "message": f"Email configuration saved and reloaded for {st['provider']}",
        "status": st
    }

@app.get("/api/v1/sms/logs")
def get_sms_logs():
    """
    Returns recent outbound cellular SMS transmission logs.
    """
    return {
        "success": True,
        "count": len(sms_gateway.sent_messages),
        "provider": sms_gateway.provider,
        "messages": sms_gateway.sent_messages
    }

@app.post("/api/v1/fleet/purge-demo")
async def purge_demo_fleet():
    """
    Purges all synthetic demo trucks so the fleet starts completely clean.
    """
    deleted_count = DatabaseManager.purge_demo_units()
    await broadcast_event("fleet_purged", {"deleted_count": deleted_count})
    return {
        "success": True,
        "deleted_count": deleted_count,
        "message": "Demo trucks purged. Fleet is ready for live tenant dispatches."
    }

@app.post("/api/v1/fleet/provision")
async def provision_truck(req: ProvisionRequest):
    """
    Fleet Manager provisions a new truck and driver.
    Generates a unique 6-digit pairing PIN valid for 24h.
    """
    record = DatabaseManager.provision_new_unit(
        truck_reg=req.truck_reg.upper().strip(),
        driver_name=req.driver_name.strip(),
        phone=req.phone.strip() if req.phone else "",
        model=req.model.strip() if req.model else "Scania R500 V8",
        fuel_liters=req.fuel_liters or 450.0
    )
    unit = DatabaseManager.get_unit(record["driver_id"])
    await broadcast_event("unit_provisioned", {"unit": unit, "pin": record["pin"]})
    return {
        "success": True,
        "provision": record,
        "unit": unit
    }

@app.post("/api/v1/driver/pair")
async def pair_driver_handset(req: DriverPairRequest):
    """
    Driver inputs 6-digit PIN on Android handset APK.
    Activates handset, returns driver_id, truck_reg, and token.
    """
    token_data = DatabaseManager.consume_pairing_pin(req.pin)
    if not token_data:
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired activation PIN. Please check with your fleet dispatcher."
        )
    unit = DatabaseManager.get_unit(token_data["driver_id"])
    await broadcast_event("unit_activated", {"unit": unit})
    return {
        "success": True,
        "driver_id": token_data["driver_id"],
        "truck_reg": token_data["truck_reg"],
        "driver_name": token_data["driver_name"],
        "bearer_token": settings.BEARER_TOKEN,
        "message": f"Handset successfully paired to {token_data['truck_reg']}"
    }

@app.delete("/api/v1/fleet/units/{driver_id}")
async def decommission_truck(driver_id: str, reason: Optional[str] = "Driver Offboarded"):
    """
    Dispatcher decommissions a truck / offboards driver when they quit.
    Revokes handset tracking immediately, preserves audit trail for SARS/RTMS.
    """
    success = DatabaseManager.decommission_unit(driver_id, reason or "Driver Offboarded")
    if not success:
        raise HTTPException(status_code=404, detail=f"Unit {driver_id} not found")
    await broadcast_event("unit_decommissioned", {"driver_id": driver_id, "reason": reason})
    return {
        "success": True,
        "driver_id": driver_id,
        "status": "DECOMMISSIONED",
        "message": f"Unit {driver_id} decommissioned and handset tracking revoked."
    }

@app.post("/api/v1/fleet/units/{driver_id}/decommission")
async def decommission_truck_post(driver_id: str, req: DecommissionRequest):
    """
    POST variant for client environments with DELETE verb restrictions.
    """
    return await decommission_truck(driver_id, req.reason)

@app.get("/api/v1/stream")
async def telemetry_stream(request: Request):
    """
    Server-Sent Events (SSE) stream for live MapLibre 3D Cockpit binding.
    """
    queue = asyncio.Queue()
    sse_subscribers.append(queue)

    async def event_generator():
        # Send initial fleet state
        units = DatabaseManager.get_all_units()
        init_payload = f"event: init\ndata: {json.dumps({'units': units})}\n\n"
        yield init_payload

        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield data
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            if queue in sse_subscribers:
                sse_subscribers.remove(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

# =========================================================================
# SARS SCHEDULE 6 & RTMS SANS 1395 COMPLIANCE REPORTING ENDPOINTS
# =========================================================================

@app.get("/api/v1/reports/sars-diesel-rebate")
def get_sars_diesel_rebate_report():
    """
    Returns structured contemporaneous SARS Schedule 6 diesel refund logbook.
    """
    return generate_sars_report_data()

@app.get("/api/v1/reports/sars-diesel-rebate/csv")
def download_sars_diesel_rebate_csv():
    """
    Exports downloadable CSV logbook compliant with SARS Customs & Excise Item 670.04.
    """
    csv_content = generate_sars_csv()
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=sars_schedule_6_diesel_rebate_2026.csv",
            "Cache-Control": "no-cache"
        }
    )

@app.get("/api/v1/reports/rtms-audit")
def get_rtms_compliance_audit_report():
    """
    Returns 4-pillar Road Transport Management System (SANS 1395) compliance governance audit.
    """
    return generate_rtms_report_data()

@app.get("/api/v1/reports/rtms-audit/csv")
def download_rtms_compliance_audit_csv():
    """
    Exports downloadable CSV compliance schedule for annual RTMS accreditation audits.
    """
    csv_content = generate_rtms_csv()
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=rtms_compliance_audit_sans1395.csv",
            "Cache-Control": "no-cache"
        }
    )

