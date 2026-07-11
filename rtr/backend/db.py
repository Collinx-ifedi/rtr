# db.py
# Production-level Database Engine & Utilities
# - Asynchronous PostgreSQL (asyncpg)
# - High-concurrency connection pooling
# - FastAPI Dependency Injection with automatic resource management

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

from .models_schemas import Base

# ======================================================
# 1. CONFIGURATION & LOGGING
# ======================================================

load_dotenv()

# Configure structured logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app.db")

raw_db_url = os.getenv("DATABASE_URL", "")

if not raw_db_url:
    logger.critical("CRITICAL: DATABASE_URL is missing! The application cannot initialize the persistence layer.")
    raise RuntimeError("DATABASE_URL is not set.")

# Production Protocol Fix:
# Cloud providers often provide 'postgres://' but SQLAlchemy Async requires 
# the 'postgresql+asyncpg://' driver for non-blocking I/O.
if raw_db_url.startswith("postgres://"):
    DATABASE_URL = raw_db_url.replace("postgres://", "postgresql+asyncpg://", 1)
elif raw_db_url.startswith("postgresql://"):
    DATABASE_URL = raw_db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
else:
    DATABASE_URL = raw_db_url

# ======================================================
# 2. ASYNC ENGINE & CONNECTION POOL
# ======================================================

# High-Performance Connection Pool Tuned for Cloud Platforms:
# pool_size: The number of connections to keep open in the pool.
# max_overflow: The number of connections to allow beyond pool_size during traffic spikes.
engine: AsyncEngine = create_async_engine(
    DATABASE_URL,
    echo=False,  # Set to True only for local debugging; logs every SQL query
    pool_size=10, 
    max_overflow=20,
    pool_timeout=30,
    pool_pre_ping=True,  # Automatically detects and replaces stale connections
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# ======================================================
# 3. FASTAPI DEPENDENCY INJECTION
# ======================================================

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency: Provides an async database session per request.
    The 'async with' context manager ensures the session is cleaned up,
    rolled back on error, and returned to the connection pool automatically.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            # Note: Explicit commits are handled within the service layer 
            # to ensure business logic validates successfully before saving.
        except Exception as e:
            logger.error(f"Database session rolled back due to error: {str(e)}")
            await session.rollback()
            raise
        # The 'finally' close block is implicitly handled by the context manager.

# ======================================================
# 4. INITIALIZATION & HEALTH CHECKS
# ======================================================

async def init_db() -> None:
    """
    Creates tables based on models_schemas.py definitions.
    For production, use Alembic for schema migrations instead.
    """
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database schema initialized successfully.")
    except Exception as e:
        logger.critical(f"Database schema initialization failed: {str(e)}")
        raise

async def ping_db() -> bool:
    """
    Health check function for monitoring. Verifies connectivity to the DB.
    """
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.error(f"Database health check failed: {str(e)}")
        return False