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
        self.smtp_host = os.getenv("SMTP_HOST", "").strip()
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.smtp_user = os.getenv("SMTP_USER", "").strip()
        raw_pass = os.getenv("SMTP_PASS", "").strip()
        if "gmail" in self.smtp_host.lower():
            self.smtp_pass = raw_pass.replace(" ", "")
        else:
            self.smtp_pass = raw_pass
        self.from_email = os.getenv("EMAIL_FROM", "dispatch@fleetwatch.co.za").strip()
        self.from_name = os.getenv("EMAIL_FROM_NAME", "FleetWatch Operations").strip()
        is_live = bool(self.smtp_host and self.smtp_user)
        logger.info(f"Initialized Email Gateway: mode={'LIVE_SMTP (' + self.smtp_host + ')' if is_live else 'LOCAL_SIMULATION'}")

    def get_status(self) -> dict:
        is_configured = bool(self.smtp_host and self.smtp_user)
        return {
            "configured": is_configured,
            "mode": "LIVE_SMTP" if is_configured else "LOCAL_SIMULATION",
            "smtp_host": self.smtp_host if is_configured else "smtp.gmail.com (Default preset)",
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

        if not self.smtp_host or not self.smtp_user:
            # Local Simulation / Dev Mode
            logger.info(f"📧 [OUTBOUND EMAIL (SIMULATION)] To: {clean_to}")
            logger.info(f"   Subject: \"{subject}\"")
            logger.info(f"   Status: Delivered (Local Simulation / Dev)")
            record["status"] = "DELIVERED_MOCK"
        else:
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

        self.sent_emails.insert(0, record)
        if len(self.sent_emails) > 100:
            self.sent_emails.pop()
        return record

    def send_test_email(self, to_email: str) -> dict:
        subject = "🧪 FleetWatch Live SMTP Verification Test"
        text_body = f"""
FleetWatch Telematics - Live SMTP Gateway Test
==============================================
This test email confirms that your SMTP gateway is actively configured and operational.

Gateway Host: {self.smtp_host or 'Local Simulation'}
Gateway Port: {self.smtp_port}
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
      <p style="margin: 4px 0 0 0; font-size: 12px; color: #34d399;">Live SMTP Gateway Verification</p>
    </div>
    <div style="background: #ecfdf5; border: 1px solid #a7f3d0; border-radius: 10px; padding: 14px; margin-bottom: 18px; text-align: center;">
      <span style="font-size: 14px; font-weight: bold; color: #065f46;">✅ Real SMTP Delivery Connected</span>
    </div>
    <p style="font-size: 13px; line-height: 1.6; color: #334155;">
      Your outbound email provider is now operational. Dispatched drivers will receive rich HTML boarding passes with immediate 6-digit in-cab OTP codes.
    </p>
    <table style="width: 100%; font-size: 12px; font-family: monospace; background: #f1f5f9; border-radius: 8px; padding: 10px; margin: 16px 0;">
      <tr><td style="color: #64748b;">Host:</td><td style="font-weight: bold; color: #0f172a;">{self.smtp_host}</td></tr>
      <tr><td style="color: #64748b;">Port:</td><td style="font-weight: bold; color: #0f172a;">{self.smtp_port}</td></tr>
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
