# core.py
# Production-level core system logic
# - Async JWT Authentication (Access & Refresh tokens)
# - Role-Based Access Control (RBAC)
# - Global Configuration Management (Pydantic V2)
# - Dynamic Path Resolution for Static Assets
# - Cryptography: Argon2 (GPU-resistant)

import os
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Union

from fastapi import HTTPException, Depends, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

# Pydantic V2 Settings
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import ValidationError, Field

from .db import get_db
from .models_schemas import User, Admin, AdminRole

# Configure Logger
logger = logging.getLogger("app.core")

# ======================================================
# 0. DYNAMIC PATH RESOLUTION
# ======================================================
# Calculate absolute paths relative to this file to avoid "File Not Found" in prod.
_CORE_FILE_PATH = os.path.abspath(__file__)          
_BACKEND_DIR = os.path.dirname(_CORE_FILE_PATH)      
_PROJECT_ROOT = os.path.dirname(_BACKEND_DIR)        
_RESOLVED_FRONTEND_PATH = os.path.join(_PROJECT_ROOT, "frontend")

# ======================================================
# 1. SYSTEM SETTINGS CONFIGURATION (PYDANTIC V2)
# ======================================================
class Settings(BaseSettings):
    # App Settings
    ENV: str = Field(default="production")
    DEBUG: bool = Field(default=False)
    LOG_LEVEL: str = Field(default="INFO")

    # Base URL of the frontend — used to build the Paystack callback_url so customers
    # land back on the storefront after paying, cancelling, or a failed charge.
    FRONTEND_URL: str = Field(default="http://localhost:3000")
    
    # Admin Seeding Strings
    ADMIN_USERNAMES: Optional[str] = Field(default=None)
    ADMIN_PASSWORDS: Optional[str] = Field(default=None)
    
    # Security Secrets
    SECRET_KEY: str = Field(...)
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # CORS Settings
    BACKEND_CORS_ORIGINS: List[str] = Field(default=["http://localhost:3000", "http://localhost:8000"])

    # Infrastructure Strings
    DATABASE_URL: str = Field(...)
    REDIS_URL: Optional[str] = Field(default=None) # Added for CMS Caching
    CLOUDINARY_URL: Optional[str] = Field(default=None)
    
    # AI Customization Configuration
    REPLICATE_API_TOKEN: Optional[str] = Field(default=None)
    
    # Paystack Configuration
    PAYSTACK_SECRET_KEY: str = Field(...)
    
    # Brevo Configuration
    BREVO_API_KEY: str = Field(...)
    SENDER_EMAIL: str = Field(...)
    
    # Asset Management Paths
    FRONTEND_DIR_PATH: str = Field(default=_RESOLVED_FRONTEND_PATH)

    # Storefront Integrations
    WHATSAPP_PHONE: str = Field(default="2340000000000")
    LIVECHAT_LICENSE: Optional[str] = Field(default=None)
    SOCIAL_FACEBOOK: Optional[str] = Field(default=None)
    SOCIAL_INSTAGRAM: Optional[str] = Field(default=None)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

try:
    settings = Settings()
except ValidationError as e:
    logger.critical(f"Missing required environment variables: {e.errors()}")
    raise RuntimeError(f"System Configuration Error: {e}")

# ======================================================
# 2. CRYPTOGRAPHY LAYER (ARGON2ID)
# ======================================================
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

def hash_password(password: str) -> str:
    """Hashes plain text credentials using secure Argon2id iteration parameters."""
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifies clear text password against storage database hash safely."""
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception as e:
        logger.error(f"Password runtime validation verification exception: {str(e)}")
        return False

# ======================================================
# 3. JWT TOKEN UTILITIES
# ======================================================
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Generates an asymmetric transient authorization Access Token."""
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

def create_refresh_token(data: dict) -> str:
    """Generates a long-lived persistence session token to grant new access tokens."""
    expire = datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode = data.copy()
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

# ======================================================
# 4. SECURITY BEARER HANDLERS
# ======================================================
class JWTBearer(HTTPBearer):
    def __init__(self, auto_error: bool = True):
        super(JWTBearer, self).__init__(auto_error=auto_error)

    async def __call__(self, request: Request) -> Optional[HTTPAuthorizationCredentials]:
        credentials = await super(JWTBearer, self).__call__(request)
        if credentials:
            if credentials.scheme != "Bearer":
                raise HTTPException(status_code=403, detail="Invalid authentication scheme. Bearer required.")
            return credentials
        return None

security_agent = JWTBearer()

# ======================================================
# 5. ASYNC CORE SYSTEM DEPENDENCIES
# ======================================================
async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security_agent),
    db: AsyncSession = Depends(get_db)
) -> User:
    """
    Decodes the transient user session token, parses user scopes, 
    and validates execution privileges against the persistent storage layer.
    """
    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        email: str = payload.get("sub")
        token_type: str = payload.get("type")
        
        if email is None or token_type != "access":
            raise HTTPException(status_code=401, detail="Invalid token properties or incorrect scope configuration.")
            
    except JWTError:
        raise HTTPException(status_code=401, detail="Authentication token could not be verified.")

    stmt = select(User).where(User.email == email)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(status_code=404, detail="User instance not present in storage.")
    if user.is_banned:
        raise HTTPException(status_code=403, detail="This user account has been administratively suspended.")
        
    return user

async def get_current_admin(
    credentials: HTTPAuthorizationCredentials = Depends(security_agent),
    db: AsyncSession = Depends(get_db)
) -> Admin:
    """
    Decodes systemic authorization tokens to identify high privilege dashboard agents.
    """
    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        username: str = payload.get("sub")
        token_type: str = payload.get("type")
        
        if username is None or token_type != "access":
            raise HTTPException(status_code=401, detail="Invalid administrative context permissions inside current scope.")
            
    except JWTError:
        raise HTTPException(status_code=401, detail="Administrative authorization credentials signature broken.")

    stmt = select(Admin).where(Admin.username == username)
    result = await db.execute(stmt)
    admin = result.scalar_one_or_none()
    
    if not admin:
        raise HTTPException(status_code=404, detail="Admin record could not be found.")
    if not admin.is_active:
        raise HTTPException(status_code=403, detail="Administrative access token assigned to an inactive operational branch.")
        
    return admin

# ======================================================
# 6. ROLE-BASED ACCESS CONTROL (RBAC)
# ======================================================
class RoleChecker:
    """
    Dependency for granular role permission enforcement across specific administration endpoints.
    Usage: Depends(RoleChecker([AdminRole.SUPERADMIN, AdminRole.MANAGER]))
    """
    def __init__(self, allowed_roles: List[AdminRole]):
        self.allowed_roles = allowed_roles

    def __call__(self, admin: Admin = Depends(get_current_admin)) -> Admin:
        if admin.role not in self.allowed_roles:
            logger.warning(f"Admin '{admin.username}' (Assigned Role: {admin.role.value}) attempted unprivileged operations.")
            raise HTTPException(
                status_code=403, 
                detail=f"Operation requires explicit validation of one of these privileges: {[r.value for r in self.allowed_roles]}"
            )
        return admin

# Pre-configured Static Security Dependency Instances
require_superadmin = RoleChecker([AdminRole.SUPERADMIN])
require_management = RoleChecker([AdminRole.SUPERADMIN, AdminRole.ADMIN, AdminRole.MANAGER])

# ======================================================
# 7. UTILITIES & SECURITY HELPERS
# ======================================================
def generate_random_token(length: int = 32) -> str:
    """Generates a cryptographically strong, URL-safe baseline string token."""
    import secrets
    return secrets.token_urlsafe(length)

def current_utc_time() -> datetime:
    """Standard systemic baseline time retrieval function."""
    return datetime.utcnow()
