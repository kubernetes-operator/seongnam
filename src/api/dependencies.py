"""공통 의존성 — DB 풀, API Key 인증."""
import os
import logging
from fastapi import HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

logger = logging.getLogger(__name__)
_security = HTTPBearer()

API_KEY = os.environ.get("API_KEY", "")


async def startup() -> None:
    from db.pool import get_pool
    from db.schema import init_schema
    pool = await get_pool()
    await init_schema(pool)
    logger.info("DB 연결 및 스키마 초기화 완료")


async def shutdown() -> None:
    from db.pool import close_pool
    await close_pool()


async def get_pool():
    from db.pool import get_pool as _get_pool
    return await _get_pool()


def verify_api_key(credentials: HTTPAuthorizationCredentials = Security(_security)):
    if API_KEY and credentials.credentials != API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
    return credentials.credentials
