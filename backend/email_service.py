"""
FleetWatch Driver Email Notification Service
============================================
Provides email dispatch of in-cab onboarding links and 6-digit OTP codes.
Supports standard SMTP (Gmail, Outlook, Amazon SES, SendGrid) and Local Simulation.
"""

import os
import re
import smtplib
import logging
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone
from typing import Optional

from pathlib import Path
from dotenv import load_dotenv

# Auto-load .env from project root
ENV_PATH = Path(__file__).parent.parent / ".env"
load_dotenv(ENV_PATH)

logger = logging.getLogger("email_service")
logger.setLevel(logging.INFO)
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("[%(asctime)s] [Email Gateway] %(message)s"))
    logger.addHandler(ch)


class EmailService:
    def __init__(self):
        self.reload_config()
        self.sent_emails: list[dict] = []

    def reload_config(self):
        load_dotenv(ENV_PATH, override=True)
        self.provider_pref = os.getenv("EMAIL_PROVIDER", "").strip().lower()
        self.sendgrid_api_key = os.getenv("SENDGRID_API_KEY", "").strip()
        self.resend_api_key = os.getenv("RESEND_API_KEY", "").strip()
        self.brevo_api_key = os.getenv("BREVO_API_KEY", "").strip()
        self.smtp_host = os.getenv("SMTP_HOST", "").strip()
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.smtp_user = os.getenv("SMTP_USER", "").strip()
        raw_pass = os.getenv("SMTP_PASS", "").strip()
        if "gmail" in self.smtp_host.lower():
            self.smtp_pass = raw_pass.replace(" ", "")
        else:
            self.smtp_pass = raw_pass
        self.from_email = os.getenv("EMAIL_FROM", "smxtechnologies1@gmail.com").strip()
        self.from_name = os.getenv("EMAIL_FROM_NAME", "FleetWatch Operations").strip()
        
        # Resolve active delivery channel
        if self.provider_pref == "sendgrid" and self.sendgrid_api_key:
            self.active_mode = "SENDGRID_API"
        elif self.provider_pref == "resend" and self.resend_api_key:
            self.active_mode = "RESEND_API"
        elif self.provider_pref == "brevo" and self.brevo_api_key:
            self.active_mode = "BREVO_API"
        elif self.provider_pref == "smtp" and self.smtp_host and self.smtp_user:
            self.active_mode = "LIVE_SMTP"
        elif self.sendgrid_api_key:
            self.active_mode = "SENDGRID_API"
        elif self.resend_api_key:
            self.active_mode = "RESEND_API"
        elif self.brevo_api_key:
            self.active_mode = "BREVO_API"
        elif self.smtp_host and self.smtp_user:
            self.active_mode = "LIVE_SMTP"
        else:
            self.active_mode = "LOCAL_SIMULATION"
            
        logger.info(f"Initialized Email Gateway: active_mode={self.active_mode} (pref={self.provider_pref or 'auto'})")

    def get_status(self) -> dict:
        is_sendgrid = bool(self.sendgrid_api_key)
        is_resend = bool(self.resend_api_key)
        is_brevo = bool(self.brevo_api_key)
        is_smtp = bool(self.smtp_host and self.smtp_user)
        is_configured = self.active_mode in ("SENDGRID_API", "RESEND_API", "BREVO_API", "LIVE_SMTP")
        
        provider_name = {
            "SENDGRID_API": "SendGrid HTTP API",
            "RESEND_API": "Resend HTTP API",
            "BREVO_API": "Brevo HTTP API",
            "LIVE_SMTP": "SMTP Gateway"
        }.get(self.active_mode, "Local Simulation")

        return {
            "configured": is_configured,
            "mode": self.active_mode,
            "provider_pref": self.provider_pref or ("sendgrid" if is_sendgrid else ("resend" if is_resend else ("brevo" if is_brevo else ("smtp" if is_smtp else "auto")))),
            "provider": provider_name,
            "sendgrid_configured": is_sendgrid,
            "resend_configured": is_resend,
            "brevo_configured": is_brevo,
            "smtp_configured": is_smtp,
            "smtp_host": self.smtp_host if is_smtp else "smtp.gmail.com (Default preset)",
            "smtp_port": self.smtp_port,
            "from_email": self.from_email,
            "from_name": self.from_name,
            "user_configured": bool(self.smtp_user),
            "pass_configured": bool(self.smtp_pass)
        }

    @staticmethod
    def is_valid_email(email: str) -> bool:
        pattern = r"^[\w\.-]+@[\w\.-]+\.\w+$"
        return bool(re.match(pattern, email.strip()))

    def send_email(self, to_email: str, subject: str, html_body: str, text_body: str) -> dict:
        timestamp = datetime.now(timezone.utc).isoformat()
        clean_to = to_email.strip()

        record = {
            "to": clean_to,
            "subject": subject,
            "html": html_body,
            "text": text_body,
            "timestamp": timestamp,
            "status": "SENT"
        }

        # 1. Preferred Cloud Delivery: SendGrid HTTP API (Port 443 HTTPS)
        if self.active_mode == "SENDGRID_API" and self.sendgrid_api_key:
            try:
                url = "https://api.sendgrid.com/v3/mail/send"
                headers = {
                    "Authorization": f"Bearer {self.sendgrid_api_key}",
                    "Content-Type": "application/json"
                }
                payload = {
                    "personalizations": [
                        {"to": [{"email": clean_to}]}
                    ],
                    "from": {
                        "email": self.from_email or "smxtechnologies1@gmail.com",
                        "name": self.from_name or "FleetWatch Operations"
                    },
                    "subject": subject,
                    "content": [
                        {"type": "text/plain", "value": text_body},
                        {"type": "text/html", "value": html_body}
                    ]
                }
                resp = requests.post(url, headers=headers, json=payload, timeout=12)
                if resp.status_code in (200, 201, 202):
                    logger.info(f"✅ SendGrid HTTP delivery succeeded to {clean_to}")
                    record["status"] = "DELIVERED_SENDGRID"
                    record["message_id"] = resp.headers.get("X-Message-Id", "")
                else:
                    err_msg = f"SendGrid HTTP {resp.status_code}: {resp.text}"
                    logger.error(f"❌ SendGrid delivery error to {clean_to}: {err_msg}")
                    record["status"] = "FAILED"
                    record["error"] = err_msg
            except Exception as e:
                logger.error(f"❌ SendGrid delivery exception to {clean_to}: {e}")
                record["status"] = "FAILED"
                record["error"] = str(e)

        # 2. Resend HTTP API (Port 443 HTTPS)
        elif self.active_mode == "RESEND_API" and self.resend_api_key:
            try:
                url = "https://api.resend.com/emails"
                headers = {
                    "Authorization": f"Bearer {self.resend_api_key}",
                    "Content-Type": "application/json"
                }
                sender_email = self.from_email if ("@" in self.from_email and not self.from_email.endswith("@gmail.com")) else "onboarding@resend.dev"
                sender_str = f"{self.from_name} <{sender_email}>" if self.from_name else sender_email
                payload = {
                    "from": sender_str,
                    "to": [clean_to],
                    "subject": subject,
                    "html": html_body,
                    "text": text_body
                }
                resp = requests.post(url, headers=headers, json=payload, timeout=12)
                if resp.status_code in (200, 201, 202):
                    logger.info(f"✅ Resend HTTP delivery succeeded to {clean_to}")
                    record["status"] = "DELIVERED_RESEND"
                    record["message_id"] = resp.json().get("id", "")
                else:
                    err_msg = f"Resend HTTP {resp.status_code}: {resp.text}"
                    logger.error(f"❌ Resend delivery error to {clean_to}: {err_msg}")
                    record["status"] = "FAILED"
                    record["error"] = err_msg
            except Exception as e:
                logger.error(f"❌ Resend delivery exception to {clean_to}: {e}")
                record["status"] = "FAILED"
                record["error"] = str(e)

        # 3. Brevo HTTP API (Port 443 - Legacy / Fallback)
        elif self.active_mode == "BREVO_API" and self.brevo_api_key:
            try:
                url = "https://api.brevo.com/v3/smtp/email"
                headers = {
                    "accept": "application/json",
                    "api-key": self.brevo_api_key,
                    "content-type": "application/json"
                }
                payload = {
                    "sender": {
                        "name": self.from_name or "FleetWatch Operations",
                        "email": self.from_email or "smxtechnologies1@gmail.com"
                    },
                    "to": [
                        {"email": clean_to}
                    ],
                    "subject": subject,
                    "htmlContent": html_body,
                    "textContent": text_body
                }
                resp = requests.post(url, headers=headers, json=payload, timeout=12)
                if resp.status_code in (200, 201, 202):
                    logger.info(f"✅ Brevo HTTP delivery succeeded to {clean_to}")
                    record["status"] = "DELIVERED_BREVO"
                    record["message_id"] = resp.json().get("messageId", "")
                else:
                    err_msg = f"Brevo HTTP {resp.status_code}: {resp.text}"
                    logger.error(f"❌ Brevo delivery error to {clean_to}: {err_msg}")
                    record["status"] = "FAILED"
                    record["error"] = err_msg
            except Exception as e:
                logger.error(f"❌ Brevo delivery exception to {clean_to}: {e}")
                record["status"] = "FAILED"
                record["error"] = str(e)

        # 4. Traditional SMTP Delivery (Port 587 / 465 for local dev or unblocked servers)
        elif self.active_mode == "LIVE_SMTP" and self.smtp_host and self.smtp_user:
            try:
                msg = MIMEMultipart("alternative")
                msg["Subject"] = subject
                msg["From"] = f"{self.from_name} <{self.from_email}>"
                msg["To"] = clean_to

                part1 = MIMEText(text_body, "plain")
                part2 = MIMEText(html_body, "html")
                msg.attach(part1)
                msg.attach(part2)

                if self.smtp_port == 465:
                    with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=12) as server:
                        server.login(self.smtp_user, self.smtp_pass)
                        server.sendmail(self.from_email, clean_to, msg.as_string())
                else:
                    with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=12) as server:
                        server.starttls()
                        server.login(self.smtp_user, self.smtp_pass)
                        server.sendmail(self.from_email, clean_to, msg.as_string())

                logger.info(f"✅ SMTP live delivery succeeded to {clean_to} via {self.smtp_host}")
                record["status"] = "DELIVERED_SMTP"
            except Exception as e:
                logger.error(f"❌ SMTP delivery failed to {clean_to} via {self.smtp_host}: {e}")
                record["status"] = "FAILED"
                record["error"] = str(e)

        # 5. Local Simulation / Dev Mode
        else:
            logger.info(f"📧 [OUTBOUND EMAIL (SIMULATION)] To: {clean_to}")
            logger.info(f"   Subject: \"{subject}\"")
            logger.info(f"   Status: Delivered (Local Simulation / Dev)")
            record["status"] = "DELIVERED_MOCK"

        self.sent_emails.insert(0, record)
        if len(self.sent_emails) > 100:
            self.sent_emails.pop()
        return record

    def send_test_email(self, to_email: str) -> dict:
        if self.active_mode == "SENDGRID_API":
            provider_name = "SendGrid HTTP API (Port 443)"
        elif self.active_mode == "RESEND_API":
            provider_name = "Resend HTTP API (Port 443)"
        elif self.active_mode == "BREVO_API":
            provider_name = "Brevo HTTP API (Port 443)"
        elif self.active_mode == "LIVE_SMTP":
            provider_name = f"SMTP ({self.smtp_host}:{self.smtp_port})"
        else:
            provider_name = "Local Simulation"
        subject = "🧪 FleetWatch Live Email Verification Test"
        text_body = f"""
FleetWatch Telematics - Live Email Gateway Test
==============================================
This test email confirms that your email gateway is actively configured and operational.

Provider: {provider_name}
From: {self.from_name} <{self.from_email}>
Timestamp: {datetime.now(timezone.utc).isoformat()}

Your driver dispatch passes and 6-digit in-cab OTP codes are now ready for live email delivery!
"""
        html_body = f"""
<!DOCTYPE html>
<html>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f8fafc; padding: 24px; color: #1e293b;">
  <div style="max-width: 500px; margin: 0 auto; background: white; border-radius: 16px; padding: 28px; border: 1px solid #e2e8f0; box-shadow: 0 4px 12px rgba(0,0,0,0.05);">
    <div style="background: #0f172a; color: white; padding: 18px; border-radius: 12px; text-align: center; margin-bottom: 20px;">
      <h2 style="margin: 0; font-size: 18px;">🛡️ FleetWatch Operations</h2>
      <p style="margin: 4px 0 0 0; font-size: 12px; color: #34d399;">Live Email Gateway Verification</p>
    </div>
    <div style="background: #ecfdf5; border: 1px solid #a7f3d0; border-radius: 10px; padding: 14px; margin-bottom: 18px; text-align: center;">
      <span style="font-size: 14px; font-weight: bold; color: #065f46;">✅ Real Delivery Connected ({provider_name})</span>
    </div>
    <p style="font-size: 13px; line-height: 1.6; color: #334155;">
      Your outbound email provider is now operational. Dispatched drivers will receive rich HTML boarding passes with immediate 6-digit in-cab OTP codes.
    </p>
    <table style="width: 100%; font-size: 12px; font-family: monospace; background: #f1f5f9; border-radius: 8px; padding: 10px; margin: 16px 0;">
      <tr><td style="color: #64748b;">Provider:</td><td style="font-weight: bold; color: #0f172a;">{provider_name}</td></tr>
      <tr><td style="color: #64748b;">Sender:</td><td style="font-weight: bold; color: #0f172a;">{self.from_email}</td></tr>
    </table>
    <p style="font-size: 11px; color: #94a3b8; text-align: center; margin-top: 20px; border-top: 1px solid #f1f5f9; padding-top: 14px;">
      FleetWatch Autonomous Freight Telematics &bull; N4 Highveld Artery
    </p>
  </div>
</body>
</html>
"""
        return self.send_email(to_email, subject, html_body, text_body)

    def send_dispatch_invite(
        self,
        to_email: str,
        truck_reg: str,
        driver_name: str,
        download_url: str,
        otp_code: str
    ) -> dict:
        first_name = driver_name.split()[0] if driver_name else "Driver"
        subject = f"🚛 FleetWatch In-Cab Dispatch Pass: {truck_reg} (Code: {otp_code})"

        text_body = f"""
FleetWatch Commercial Freight Telematics
=========================================
Hello {first_name},

You have been dispatched for vehicle: {truck_reg}
Your 6-Digit In-Cab Login Code: {otp_code}

Instructions to Start Transit:
1. Download & install the FleetSentinel Driver APK:
   {download_url}

2. Open the app, enter your 6-digit login code: {otp_code}

3. Tap 'Verify & Start Tracking'. Background GPS telematics will begin automatically.

Safe journey on the N4 Highveld Artery!
FleetWatch Operations Dispatch
"""

        html_body = f"""
<!DOCTYPE html>
<html>
<head>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #f8fafc; color: #1e293b; padding: 20px; }}
    .card {{ background: #ffffff; max-width: 540px; margin: 0 auto; border-radius: 16px; border: 1px solid #e2e8f0; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); }}
    .header {{ background: #0f172a; color: #ffffff; padding: 24px; text-align: center; }}
    .content {{ padding: 24px; line-height: 1.6; }}
    .otp-box {{ background: #ecfdf5; border: 2px dashed #10b981; border-radius: 12px; padding: 18px; text-align: center; margin: 20px 0; }}
    .otp-code {{ font-size: 32px; font-weight: 800; letter-spacing: 4px; color: #047857; font-family: monospace; }}
    .btn {{ display: block; background: #10b981; color: #ffffff; text-decoration: none; padding: 14px 20px; border-radius: 10px; font-weight: bold; text-align: center; margin: 20px 0; }}
    .footer {{ font-size: 11px; color: #94a3b8; text-align: center; padding: 16px; border-top: 1px solid #e2e8f0; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="header">
      <h2 style="margin: 0; font-size: 20px;">🛡️ FleetWatch Operations</h2>
      <p style="margin: 4px 0 0 0; font-size: 13px; color: #34d399;">N4 Highveld Corridor Driver Dispatch</p>
    </div>
    <div class="content">
      <p>Hello <strong>{first_name}</strong>,</p>
      <p>You have been assigned to vehicle <strong>{truck_reg}</strong>. Your in-cab driver credentials have been generated:</p>
      
      <div class="otp-box">
        <div style="font-size: 11px; text-transform: uppercase; font-weight: bold; color: #065f46; margin-bottom: 4px;">Your 6-Digit In-Cab Login Code</div>
        <div class="otp-code">{otp_code}</div>
        <div style="font-size: 11px; color: #047857; margin-top: 4px;">Valid for in-cab login &amp; verification</div>
      </div>

      <p style="font-size: 13px;"><strong>Next Steps:</strong></p>
      <ol style="font-size: 13px; padding-left: 20px; color: #475569;">
        <li>Download the driver app:</li>
      </ol>
      <a href="{download_url}" class="btn">📥 Download FleetSentinel Driver App</a>
      <ol start="2" style="font-size: 13px; padding-left: 20px; color: #475569;">
        <li>Open the app and enter code <strong>{otp_code}</strong>.</li>
        <li>Tap <strong>Verify &amp; Start Tracking</strong>. Live compliance telematics will begin.</li>
      </ol>
    </div>
    <div class="footer">
      FleetWatch Autonomous Telemetry &bull; Pretoria &harr; Witbank Artery &bull; SARS Schedule 6 Logbook Compliant
    </div>
  </div>
</body>
</html>
"""
        return self.send_email(to_email, subject, html_body, text_body)

    def send_login_otp(
        self,
        to_email: str,
        otp_code: str,
        truck_reg: str,
        driver_name: str = "Driver"
    ) -> dict:
        first_name = driver_name.split()[0] if driver_name else "Driver"
        subject = f"🔑 FleetWatch In-Cab Login Code: {otp_code} ({truck_reg})"

        text_body = f"""
Hello {first_name},

Your requested in-cab login code for {truck_reg} is: {otp_code}
Enter this code in your FleetSentinel Android app to authenticate and start transit.
Code expires in 15 minutes.
"""
        html_body = f"""
<!DOCTYPE html>
<html>
<body style="font-family: sans-serif; background: #f8fafc; padding: 20px; color: #1e293b;">
  <div style="max-width: 480px; margin: 0 auto; background: white; border-radius: 14px; padding: 24px; border: 1px solid #e2e8f0;">
    <h3 style="margin-top: 0; color: #0f172a;">🔑 In-Cab Verification Code</h3>
    <p>Hi {first_name}, your login code for vehicle <strong>{truck_reg}</strong> is:</p>
    <div style="background: #ecfdf5; border: 2px dashed #10b981; border-radius: 10px; padding: 14px; text-align: center; margin: 16px 0;">
      <span style="font-size: 32px; font-weight: bold; font-family: monospace; color: #047857; letter-spacing: 4px;">{otp_code}</span>
    </div>
    <p style="font-size: 12px; color: #64748b;">Enter this code into your FleetSentinel app. Code is valid for 15 minutes.</p>
  </div>
</body>
</html>
"""
        return self.send_email(to_email, subject, html_body, text_body)


# Shared singleton instance
email_gateway = EmailService()
