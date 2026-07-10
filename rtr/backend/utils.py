# utils.py
# Production-level utility functions
# Rocky Trendy Realities - Physical Furniture & AI Customizer
# - Async Email sending (Brevo) with Retries
# - Cryptographically secure OTPs
# - Structured JSON Logging
# - Data export & formatting

import os
import csv
import logging
import secrets
import json
import httpx
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any, Union

from dotenv import load_dotenv

# Enum is imported to keep type hints clean
from .models_schemas import OTPPurpose

# ======================================================
# CONFIGURATION & VALIDATION
# ======================================================

load_dotenv()

BREVO_API_KEY = os.getenv("BREVO_API_KEY")
SENDER_EMAIL = os.getenv("SENDER_EMAIL")

# Fail fast if critical env vars are missing
if not BREVO_API_KEY or not SENDER_EMAIL:
    logging.critical("CRITICAL: BREVO_API_KEY or SENDER_EMAIL is missing. Email services will fail.")


# ======================================================
# STRUCTURED LOGGING
# ======================================================

class JSONFormatter(logging.Formatter):
    """
    Formatter to output logs in JSON format for production monitoring systems (ELK, Datadog, etc.)
    Captures business-critical metadata like order references and AI tracking events.
    """
    def format(self, record):
        log_obj = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
            "func": record.funcName,
            "line": record.lineno,
        }
        if hasattr(record, 'request_id'):
            log_obj['request_id'] = record.request_id
        
        # Merge structured metadata if present
        if hasattr(record, 'meta') and isinstance(record.meta, dict):
            log_obj.update(record.meta)
            
        return json.dumps(log_obj)

# Setup Logger
handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logger = logging.getLogger("app.utils")
logger.setLevel(logging.INFO)
logger.addHandler(handler)
logger.propagate = False

def log_action(
    action: str, 
    actor: str = "system", 
    ip_address: Optional[str] = None, 
    metadata: Optional[dict] = None,
    order_reference: Optional[str] = None
):
    """
    Centralized auditing helper.
    Automatically merges specific business keys into the metadata for easier indexing.
    """
    meta = metadata or {}
    
    if order_reference:
        meta['order_reference'] = order_reference

    log_data = {
        "event": "audit_log",
        "action": action,
        "actor": actor,
        "ip": ip_address,
        "meta": meta
    }
    logger.info(json.dumps(log_data))


# ======================================================
# ASYNC EMAIL SERVICE (BREVO)
# ======================================================

async def send_email_async(
    recipient_email: str, 
    subject: str, 
    html_content: str, 
    retries: int = 3
) -> bool:
    """
    Asynchronously send an email using Brevo API with automatic retries.
    """
    url = "https://api.brevo.com/v3/smtp/email"
    headers = {
        "api-key": BREVO_API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    payload = {
        "sender": {"name": "Columbus", "email": SENDER_EMAIL},
        "to": [{"email": recipient_email}],
        "subject": subject,
        "htmlContent": html_content
    }

    async with httpx.AsyncClient() as client:
        for attempt in range(retries):
            try:
                response = await client.post(url, json=payload, headers=headers, timeout=10.0)
                response.raise_for_status()
                logger.info(f"Email sent successfully to {recipient_email} [Subject: {subject}]")
                return True
            except httpx.HTTPStatusError as e:
                logger.error(f"Email failed (Attempt {attempt+1}/{retries}): {e.response.text}")
                if e.response.status_code in [400, 401]: # Don't retry auth/bad request errors
                    break
            except Exception as e:
                logger.error(f"Network error sending email (Attempt {attempt+1}/{retries}): {str(e)}")
                await asyncio.sleep(1) # Simple backoff
            
    return False


# ======================================================
# FULFILLMENT & NOTIFICATION TEMPLATES
# ======================================================

async def send_fulfillment_email(
    user_email: str, 
    product_name: str, 
    order_reference: str,
    manual_text: Optional[str] = None
) -> bool:
    """
    Unified order status email handler for physical shipments.
    """
    subject = f"Order Status Update: {product_name} (#{order_reference})"
    
    content_html = ""

    # Section A: Manual Admin Note / Shipping Instructions
    if manual_text:
        content_html += f"""
        <div style="background-color: #fffbeb; padding: 15px; border-left: 4px solid #d97706; margin: 10px 0;">
            <pre style="font-family: Arial, sans-serif; white-space: pre-wrap; margin: 0; color: #333;">{manual_text}</pre>
        </div>
        """

    # Wrapper Template
    html_wrapper = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #333; line-height: 1.6;">
        <div style="text-align: center; padding-bottom: 20px;">
            <h1 style="margin: 0; color: #1a1a1a;">Rocky Trendy Realities</h1>
        </div>
        <h2 style="border-bottom: 2px solid #eee; padding-bottom: 10px;">Order Update</h2>
        <p>Thank you for purchasing <strong>{product_name}</strong>.</p>
        <p style="color: #666; font-size: 14px;">Order Reference: <strong>{order_reference}</strong></p>
        
        {content_html}
        
        <p style="font-size: 12px; color: #777; margin-top: 30px; border-top: 1px solid #eee; padding-top: 10px;">
            If you have trouble with your order, please reply to this email or contact our support team.
        </p>
    </div>
    """
    
    return await send_email_async(user_email, subject, html_wrapper)


# ======================================================
# OTP & SECURITY
# ======================================================

def generate_otp(length: int = 6) -> str:
    """Generate a cryptographically secure numeric OTP."""
    return ''.join(secrets.choice("0123456789") for _ in range(length))

async def send_email_otp(recipient_email: str, otp_code: str, purpose: Union[OTPPurpose, str]):
    """
    Orchestrates constructing the OTP email content and sending it.
    """
    purpose_val = purpose.value if hasattr(purpose, 'value') else str(purpose)
    
    subject_map = {
        "email_verify": "Verify Your Email Address - Rocky Trendy Realities",
        "password_reset": "Password Reset Request",
        "2fa": "Your Secure Login Code"
    }
    
    subject = subject_map.get(purpose_val, "Your Verification Code")
    
    html_content = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <div style="text-align: center; padding-bottom: 20px;">
            <h2 style="margin: 0; color: #1a1a1a;">Rocky Trendy Realities</h2>
        </div>
        <h3 style="color: #333;">{subject}</h3>
        <p>Use the following One-Time Password (OTP) to complete your action:</p>
        <div style="background-color: #f4f4f4; padding: 15px; text-align: center; font-size: 24px; letter-spacing: 5px; font-weight: bold; border-radius: 4px;">
            {otp_code}
        </div>
        <p>This code expires in 10 minutes.</p>
        <p style="color: #888; font-size: 12px;">If you did not request this, please ignore this email.</p>
    </div>
    """
    
    await send_email_async(recipient_email, subject, html_content)

async def save_otp_to_db(db, email: str, otp: str, purpose: Any, expires_minutes: int = 10):
    """
    Import OTPRecord locally to avoid circular imports.
    """
    from .models_schemas import OTPRecord
    
    expires_at = datetime.utcnow() + timedelta(minutes=expires_minutes)
    otp_record = OTPRecord(
        email=email,
        otp_hash=otp, 
        purpose=purpose,
        expires_at=expires_at,
        used=False
    )
    db.add(otp_record)
    return otp_record


# ======================================================
# DATA EXPORT & FORMATTING
# ======================================================

def export_to_csv(filename: str, data: List[Dict[str, Any]]) -> Optional[str]:
    """
    Exports a list of dictionaries to a CSV file.
    """
    if not data:
        logger.warning("Export requested but no data provided.")
        return None

    os.makedirs("exports", exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = f"exports/{filename}_{timestamp}.csv"

    try:
        fieldnames = data[0].keys()
        with open(filepath, "w", newline="", encoding="utf-8-sig") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(data)
            
        logger.info(f"Data exported successfully to {filepath}")
        return filepath
    except IOError as e:
        logger.error(f"File I/O error during CSV export: {e}")
        return None


# ======================================================
# MISC HELPERS
# ======================================================

def generate_random_token(length: int = 32) -> str:
    """Generate a secure random URL-safe token."""
    return secrets.token_urlsafe(length)

def format_currency(amount: float, currency: str = "NGN") -> str:
    """
    Standardize currency display based on operational region.
    """
    return f"{currency} {amount:,.2f}"
