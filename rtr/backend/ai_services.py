# ai_services.py
# Production-level AI Customization Layer (Hugging Face Test via OPENAI_API_KEY)
# Rocky Trendy Realities — Asynchronous Furniture Customizer & Cloud Storage

import io
import os
import logging
from datetime import datetime
from typing import Optional

import httpx
import cloudinary
import cloudinary.uploader
from fastapi import HTTPException, status

from core import settings
from utils import log_action

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
    Dedicated service handling external Hugging Face Stability Image synthesis, 
    variant generation, and direct pipeline persistence via Cloudinary.
    """

    def __init__(self) -> None:
        # Pulling OPENAI_API_KEY to avoid modifying core.py, 
        # but this will be used for the Hugging Face API test.
        self.api_key: Optional[str] = getattr(settings, "OPENAI_API_KEY", os.getenv("OPENAI_API_KEY"))
        
        # Test endpoint target: Stability AI Model on Hugging Face Inference API
        self.hf_model_url: str = "https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-3-medium-diffusers"
        
        # Verify Cloudinary configuration status
        if not getattr(settings, "CLOUDINARY_URL", os.getenv("CLOUDINARY_URL")):
            logger.critical("CRITICAL: CLOUDINARY_URL is missing. Media uploads will fail.")

    async def generate_custom_furniture_image(
        self, 
        prompt: str, 
        user_id: int, 
        product_context: Optional[str] = None
    ) -> str:
        """
        Orchestrates the creation of custom design imagery:
        1. Submits refined descriptive text to Hugging Face Inference API.
        2. Directly receives and streams the response binary image bytes.
        3. Uploads the buffer straight to Cloudinary under a specialized directory structure.
        4. Returns the production-ready HTTPS delivery URL.
        """
        if not self.api_key:
            logger.error("AI service failure: OPENAI_API_KEY is not defined in system environment.")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="API Key is missing or unconfigured."
            )

        # Build clean structural prompt matching the luxury Rocky Trendy Realities aesthetic
        base_context = product_context or "Modern Home Finishes"
        refined_prompt = (
            f"High-end luxury furniture design, photorealistic, professional interior architecture photography, "
            f"studio lighting, premium catalog style. Item context: {base_context}. "
            f"User customization adjustments: {prompt}. "
            f"Clean, neutral background emphasizing the materials and textures."
        )

        logger.info(f"Initiating Hugging Face Stability generation pipeline for user ID {user_id}...")
        
        async with httpx.AsyncClient() as client:
            try:
                # 1. Request image bytes from Hugging Face Inference Endpoint
                ai_response = await client.post(
                    self.hf_model_url,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "inputs": refined_prompt,
                        "parameters": {
                            "negative_prompt": "blurry, low quality, distorted, extra limbs, text, watermark",
                            "guidance_scale": 7.5
                        }
                    },
                    timeout=60.0 
                )
                
                # Check if model is loading
                if ai_response.status_code == 503:
                    logger.warning("Hugging Face model is currently loading into memory cluster...")
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail="The Stability model is initializing on Hugging Face. Please try again in a few moments."
                    )
                
                if ai_response.status_code != 200:
                    logger.error(f"Hugging Face Gateway rejected query with code {ai_response.status_code}: {ai_response.text}")
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail="The AI generation network returned an invalid response."
                    )
                
                # HF returns raw image payload byte stream directly
                image_bytes = ai_response.content

            except httpx.RequestError as exc:
                logger.error(f"Network transport anomaly encountered during HF communication: {str(exc)}")
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Upstream HF inference architecture is unreachable."
                )
            except HTTPException:
                raise
            except Exception as exc:
                logger.error(f"Unexpected fault processing Hugging Face synthesis context: {str(exc)}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to successfully process AI generation pipeline."
                )

        # 2. Offload cloud asset migration to secure storage bucket natively
        try:
            # Wrap the raw binary image response safely into an in-memory stream structure
            file_stream = io.BytesIO(image_bytes)
            
            # Execute standard execution call to Cloudinary uploader wrapper using custom storage pathing
            upload_result = cloudinary.uploader.upload(
                file_stream,
                folder="rtr_ai_customizer",
                tags=["hf_generated", "stability_test", f"user_{user_id}"],
                public_id=f"custom_{user_id}_{int(datetime.utcnow().timestamp())}",
                overwrite=True,
                resource_type="image"
            )
            
            secure_url: str = upload_result.get("secure_url")
            if not secure_url:
                raise ValueError("Cloudinary upload did not resolve into a verified secure URL path.")

            # Record a structured audit trail log of the event sequence
            log_action(
                action="ai_asset_generated",
                actor=f"user_{user_id}",
                metadata={"cloudinary_url": secure_url, "prompt_length": len(prompt)}
            )

            # 3. Supply direct verified cloud url to the application router framework
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
    """
    FastAPI route dependency manager supplying non-blocking instance validation.
    Usage in router: ai: AIService = Depends(get_ai_service)
    """
    return AIService()
