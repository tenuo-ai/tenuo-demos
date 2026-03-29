"""Database connection management for demo tools."""

import os
from contextvars import ContextVar

import asyncpg
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://demo:demo@localhost:5432/tenuo_demo")

_pool: asyncpg.Pool | None = None
_pool_var: ContextVar[asyncpg.Pool | None] = ContextVar("db_pool", default=None)


async def get_pool() -> asyncpg.Pool:
    """Get or create the connection pool."""
    global _pool
    # Check context-local override first (for testing)
    ctx_pool = _pool_var.get()
    if ctx_pool is not None:
        return ctx_pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    return _pool


def set_pool(pool: asyncpg.Pool) -> None:
    """Override the pool (for testing)."""
    _pool_var.set(pool)


async def close_pool() -> None:
    """Close the global pool."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
