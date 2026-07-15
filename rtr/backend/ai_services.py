# ai_services.py
# Production-level AI Customization Layer
# Rocky Trendy Realities — Asynchronous Furniture Customizer & Cloud Storage

import io
import os
import logging
from datetime import datetime
from typing import Optional

import httpx
import cloudinary
import cloudinary.uploader
import replicate
from fastapi import HTTPException, status

from .core import settings
from .utils import log_action

# =========================================================
# CONFIG & LOGGING
# =========================================================

logger = logging.getLogger("app.ai_services")
logger.setLevel(logging.INFO)

# =========================================================
# AI SERVICE CLASS
# =========================================================

class AIService:
    """
    Dedicated service handling external AI Image synthesis, variant 
    generation, and direct pipeline persistence via Cloudinary.
    """

    def __init__(self) -> None:
        # Replicate API Key 
        self.api_key: Optional[str] = getattr(settings, "REPLICATE_API_TOKEN", os.getenv("REPLICATE_API_TOKEN"))
        
        if not getattr(settings, "CLOUDINARY_URL", os.getenv("CLOUDINARY_URL")):
            logger.critical("CRITICAL: CLOUDINARY_URL is missing.")

    async def generate_custom_furniture_image(
        self, 
        prompt: str, 
        user_id: int, 
        base_image_url: str,
        product_context: Optional[str] = None
    ) -> str:
        """
        Executes a non-blocking Image-to-Image AI generation using FLUX-2-Pro
        on Replicate, persisting the result to Cloudinary.
        """
        if not self.api_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AI customization system is temporarily offline (Configuration missing)."
            )

        # Refined prompt for Flux-2-Pro to ensure the furniture context remains intact
        refined_prompt = (
            f"Change the material, color, and style of the furniture to: {prompt}. "
            f"Maintain the exact original background, room setting, and aspect ratio. "
            f"High-end studio product photography."
        )

        try:
            client = replicate.Client(api_token=self.api_key)

            # 1. Trigger Flux-2-Pro asynchronously
            output = await client.async_run(
                "black-forest-labs/flux-2-pro",
                input={
                    "prompt": refined_prompt,
                    "resolution": "1 MP",
                    "aspect_ratio": "match_input_image",
                    "input_images": [base_image_url],  # Flux requires this inside a list
                    "output_format": "jpg",
                    "output_quality": 80,              # Optimized for web speed & quality balance
                    "safety_tolerance": 2,
                    "prompt_upsampling": False
                }
            )

            # Flux returns a FileOutput object. We verify it exists before proceeding.
            if not output:
                raise ValueError("Replicate (Flux-2-Pro) failed to yield a valid output image.")
            
            # Extract the raw string URL from the FileOutput object
            ai_generated_url = str(output.url)

        except Exception as ai_err:
            logger.error(f"Replicate API processing exception occurred: {str(ai_err)}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="The AI image engine failed to process the request."
            )

        # =========================================================
        # CLOUDINARY MIGRATION PIPELINE (Unchanged & Async)
        # =========================================================
        try:
            # We use httpx to download the generated image asynchronously to avoid blocking the event loop
            async with httpx.AsyncClient() as http_client:
                image_response = await http_client.get(ai_generated_url, timeout=20.0)
                image_response.raise_for_status()
                image_bytes = image_response.content

            file_stream = io.BytesIO(image_bytes)

            # Upload the bytes to Cloudinary
            upload_result = cloudinary.uploader.upload(
                file_stream,
                folder="rtr_custom_variants",
                public_id=f"custom_{user_id}_{int(datetime.utcnow().timestamp())}",
                overwrite=True,
                resource_type="image"
            )
            
            secure_url: str = upload_result.get("secure_url")
            if not secure_url:
                raise ValueError("Cloudinary upload did not resolve into a verified secure URL path.")

            log_action(
                action="ai_asset_generated",
                actor=f"user_{user_id}",
                metadata={"cloudinary_url": secure_url, "model": "flux-2-pro"}
            )

            return secure_url

        except Exception as upload_err:
            logger.error(f"Failed to persist asset data into Cloudinary architecture safely: {str(upload_err)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Generated imagery was created successfully but failed security folder migration."
            )

# =========================================================
# SYSTEM DEPENDENCY INJECTION ENGINE
# =========================================================
async def get_ai_service() -> AIService:
    return AIService()
