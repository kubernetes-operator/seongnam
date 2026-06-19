"""asyncpg 연결 풀 관리."""
import asyncpg
import os
from contextlib import asynccontextmanager
from typing import Optional

_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        dsn = os.environ.get("DATABASE_URL")
        if not dsn:
            raise RuntimeError("DATABASE_URL 환경변수가 설정되지 않았습니다")
        _pool = await asyncpg.create_pool(
            dsn=dsn,
            min_size=5,
            max_size=20,
            command_timeout=30,
        )
    return _pool


@asynccontextmanager
async def db_conn():
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
