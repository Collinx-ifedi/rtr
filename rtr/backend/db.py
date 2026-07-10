# db.py
# Production-level Database Engine & Utilities
# - Asynchronous PostgreSQL (asyncpg)
# - High-concurrency connection pooling
# - FastAPI Dependency Injection

import os
import logging
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker,
    AsyncEngine
)
from sqlalchemy import text
from dotenv import load_dotenv

from models_schemas import Base

# ======================================================
# 1. CONFIGURATION & LOGGING
# ======================================================

load_dotenv()

# Configure structured logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app.db")

raw_db_url = os.getenv("DATABASE_URL", "")

if not raw_db_url:
    raise RuntimeError("CRITICAL: DATABASE_URL is missing! System cannot start.")

# Production Protocol Fix
# Cloud providers (Heroku/Render/AWS) often provide 'postgres://' 
# but SQLAlchemy Async requires the 'postgresql+asyncpg://' driver.
if raw_db_url.startswith("postgres://"):
    DATABASE_URL = raw_db_url.replace("postgres://", "postgresql+asyncpg://", 1)
elif raw_db_url.startswith("postgresql://"):
    DATABASE_URL = raw_db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
else:
    DATABASE_URL = raw_db_url

# ======================================================
# 2. ASYNC ENGINE & CONNECTION POOL
# ======================================================

# High-Performance Connection Pool Tuned for FastAPI
engine: AsyncEngine = create_async_engine(
    DATABASE_URL,
    echo=False,             # Set to False in production to prevent query log flooding
    future=True,
    pool_size=20,           # Hold 20 permanent connections
    max_overflow=40,        # Allow 40 temporary spikes (total 60 concurrent connections)
    pool_timeout=60,        # Wait 60s for a connection to free up before failing
    pool_pre_ping=True,     # Ping DB to ensure connection is alive before handing it out
    pool_recycle=1800,      # Recycle connections every 30 mins to prevent stale drops
)

# ======================================================
# 3. SESSION FACTORY
# ======================================================

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    autoflush=False,
    expire_on_commit=False,
)

# ======================================================
# 4. FASTAPI DEPENDENCY
# ======================================================

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency: Provides an async database session per request.
    Automatically handles commit/rollback and cleanup.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            # Note: Explicit commits are handled within the service layer 
            # to ensure business logic validates before saving.
        except Exception as e:
            logger.error(f"Database session rolled back due to error: {str(e)}")
            await session.rollback()
            raise
        finally:
            await session.close()

# ======================================================
# 5. INITIALIZATION & HEALTH CHECKS
# ======================================================

async def init_db() -> None:
    """
    Creates tables if they don't exist based on models_schemas.py.
    For strict production environments, replace this with Alembic migrations.
    """
    try:
        async with engine.begin() as conn:
            # await conn.run_sync(Base.metadata.drop_all) # UNCOMMENT TO WIPE DB (Dev Only)
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables verified and initialized successfully.")
    except Exception as e:
        logger.critical(f"Failed to initialize database schema: {str(e)}")
        raise

async def ping_db() -> bool:
    """
    Health check function to verify database responsiveness.
    """
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.error(f"Database health check failed: {str(e)}")
        return False
