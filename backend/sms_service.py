"""
South African Cellular SMS Gateway Service
Provides programmatic SMS dispatch to drivers across Vodacom, MTN, Telkom, and Cell C networks.
Supports Africa's Talking, Twilio, and Local Mock / Terminal Logging.
"""

import os
import re
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("sms_service")
logger.setLevel(logging.INFO)
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("[%(asctime)s] [SMS Gateway] %(message)s"))
    logger.addHandler(ch)

class SmsService:
    def __init__(self):
        self.provider = os.getenv("SMS_PROVIDER", "mock").lower()
        self.api_key = os.getenv("SMS_API_KEY", "")
        self.username = os.getenv("SMS_USERNAME", "sandbox")
        self.sender_id = os.getenv("SMS_SENDER_ID", "FleetWatch")
        self.sent_messages: list[dict] = []

    @staticmethod
    def normalize_phone_number(phone: str) -> str:
        """
        Normalizes South African mobile numbers into E.164 format:
        082 123 4567 -> +27821234567
        0831234567   -> +27831234567
        +27821234567 -> +27821234567
        """
        digits = re.sub(r"[^\d+]", "", phone.strip())
        if digits.startswith("0") and len(digits) == 10:
            return "+27" + digits[1:]
        elif digits.startswith("27") and len(digits) == 11:
            return "+" + digits
        elif digits.startswith("+27"):
            return digits
        return digits

    def send_sms(self, to_phone: str, message: str) -> dict:
        """
        Dispatches SMS to driver handset.
        """
        normalized_to = self.normalize_phone_number(to_phone)
        timestamp = datetime.now(timezone.utc).isoformat()
        
        record = {
            "to": normalized_to,
            "raw_phone": to_phone,
            "message": message,
            "provider": self.provider,
            "timestamp": timestamp,
            "status": "SENT"
        }

        if self.provider == "mock" or not self.api_key:
            # High-visibility terminal output for development / local testing
            logger.info(f"📱 [OUTBOUND SMS via GSM] To: {normalized_to}")
            logger.info(f"   Message: \"{message}\"")
            logger.info(f"   Network: South Africa GSM Direct (Simulated)")
            record["status"] = "DELIVERED_MOCK"
        elif self.provider == "africas_talking":
            try:
                import africastalking
                africastalking.initialize(self.username, self.api_key)
                sms = africastalking.SMS
                response = sms.send(message, [normalized_to], self.sender_id)
                logger.info(f"Africa's Talking dispatch response: {response}")
                record["provider_response"] = response
                record["status"] = "DELIVERED_TELCO"
            except Exception as e:
                logger.error(f"Africa's Talking dispatch failed: {e}")
                record["status"] = "FAILED"
                record["error"] = str(e)
        elif self.provider == "twilio":
            try:
                from twilio.rest import Client
                account_sid = os.getenv("TWILIO_ACCOUNT_SID", "")
                auth_token = self.api_key
                from_num = os.getenv("TWILIO_FROM_NUMBER", "+12055550199")
                client = Client(account_sid, auth_token)
                res = client.messages.create(body=message, from_=from_num, to=normalized_to)
                record["provider_response"] = res.sid
                record["status"] = "DELIVERED_TWILIO"
            except Exception as e:
                logger.error(f"Twilio dispatch failed: {e}")
                record["status"] = "FAILED"
                record["error"] = str(e)

        self.sent_messages.insert(0, record)
        if len(self.sent_messages) > 100:
            self.sent_messages.pop()
        return record

    def send_dispatch_invite(self, to_phone: str, truck_reg: str, driver_name: str, download_url: str) -> dict:
        """
        Sends initial onboarding invitation with app download link.
        """
        first_name = driver_name.split()[0] if driver_name else "Driver"
        message = (
            f"FleetWatch: Hi {first_name}, you are dispatched for vehicle {truck_reg}. "
            f"1. Install Driver App: {download_url} "
            f"2. Open app & tap 'Request Login Code'."
        )
        return self.send_sms(to_phone, message)

    def send_login_otp(self, to_phone: str, otp_code: str, truck_reg: str) -> dict:
        """
        Sends 6-digit login verification OTP.
        """
        message = (
            f"FleetWatch: Your in-cab login code for {truck_reg} is: {otp_code}. "
            f"Enter this code in your FleetSentinel app to start transit."
        )
        return self.send_sms(to_phone, message)

# Shared singleton instance
sms_gateway = SmsService()
