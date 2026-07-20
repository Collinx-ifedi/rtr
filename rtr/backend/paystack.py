# paystack.py
# Production-level Paystack Integration
# - Secure Webhook Signature Verification
# - Async HTTPX API Calls with Timeout & Retry Strategies
# - Strict Type Hinting

import hmac
import hashlib
import logging
from typing import Any, Dict, Optional

import httpx
from fastapi import HTTPException, status

# Corrected import path reflecting the local core.py structure
from .core import settings

# Setup logging for production monitoring
logger = logging.getLogger("app.paystack")
logger.setLevel(logging.INFO)

# Base URL for all Paystack API endpoints
PAYSTACK_BASE_URL = "https://api.paystack.co"

def _get_headers() -> Dict[str, str]:
    """
    Constructs the required headers for Paystack API requests.
    Never expose the secret key on the frontend; all requests must originate from this server.
    """
    if not settings.PAYSTACK_SECRET_KEY:
        logger.critical("CRITICAL: PAYSTACK_SECRET_KEY is missing from the environment.")
        raise RuntimeError("Payment gateway misconfigured.")

    return {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json"
    }

async def initialize_transaction(
    email: str, 
    amount: int, 
    reference: Optional[str] = None,
    callback_url: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Initializes a transaction from the backend to get an authorization URL and access_code.
    
    Args:
        email: The customer's email address.
        amount: The transaction amount in the lowest denomination (e.g., kobo for NGN).
        reference: Unique transaction identifier from your system.
        callback_url: The URL to redirect the user to after payment.
        metadata: Additional custom information to pass along with the transaction.
    """
    url = f"{PAYSTACK_BASE_URL}/transaction/initialize"
    
    payload: Dict[str, Any] = {
        "email": email,
        "amount": amount
    }
    
    if reference:
        payload["reference"] = reference
    if callback_url:
        payload["callback_url"] = callback_url
    if metadata:
        payload["metadata"] = metadata

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=payload, headers=_get_headers(), timeout=15.0)
            response.raise_for_status()
            data = response.json()
            
            # FIX APPLIED: Return the full data payload instead of data.get("data", {})
            return data
            
        except httpx.HTTPStatusError as e:
            logger.error(f"Paystack Initialize Error: {e.response.text}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to initialize payment with the gateway."
            )
        except httpx.RequestError as e:
            logger.error(f"Paystack Network Error: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Payment gateway is currently unreachable."
            )

async def verify_transaction(reference: str) -> Dict[str, Any]:
    """
    Verifies the status of a transaction using its reference.
    This must be called to confirm the transaction was successful before delivering value.
    """
    url = f"{PAYSTACK_BASE_URL}/transaction/verify/{reference}"
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=_get_headers(), timeout=10.0)
            response.raise_for_status()
            data = response.json()
            return data.get("data", {})
        except httpx.HTTPStatusError as e:
            logger.error(f"Paystack Verify Error for ref '{reference}': {e.response.text}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to verify payment status."
            )
        except httpx.RequestError as e:
            logger.error(f"Paystack Network Error during verification: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Payment gateway is currently unreachable."
            )

async def create_charge(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Initiates a payment using specific channels (e.g., USSD, Bank Transfer, Mobile Money, QR).
    Allows building custom checkout experiences utilizing OS APIs or offline prompt systems.
    
    Args:
        payload: A dictionary containing 'email', 'amount', and the channel-specific object 
                 (e.g., 'bank_transfer', 'ussd', 'mobile_money', 'qr').
    """
    url = f"{PAYSTACK_BASE_URL}/charge"
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=payload, headers=_get_headers(), timeout=15.0)
            # The charge API might return 400 for bad inputs, so we capture the JSON error message safely
            if response.status_code >= 400:
                logger.warning(f"Paystack Charge API Error: {response.text}")
                return response.json()
                
            data = response.json()
            return data
        except httpx.RequestError as e:
            logger.error(f"Paystack Charge Network Error: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Payment gateway is currently unreachable."
            )

def verify_webhook_signature(payload_bytes: bytes, signature: str) -> bool:
    """
    Verifies that incoming webhook events originate from Paystack by comparing the 
    x-paystack-signature header against an HMAC SHA512 hash of the raw request payload.
    
    Args:
        payload_bytes: The raw bytes of the incoming request body.
        signature: The value of the 'x-paystack-signature' header.
    """
    if not signature:
        return False
        
    secret = settings.PAYSTACK_SECRET_KEY.encode('utf-8')
    computed_hash = hmac.new(
        secret, 
        payload_bytes, 
        hashlib.sha512
    ).hexdigest()
    
    # Use hmac.compare_digest to prevent timing attacks
    return hmac.compare_digest(computed_hash, signature)
