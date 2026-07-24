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
    from api.auth import ensure_seed
    pool = await get_pool()
    await init_schema(pool)
    await ensure_seed(pool)  # 기본 관리자 시드(admin/password) — 즉시 변경 권장
    logger.info("DB 연결 및 스키마 초기화 완료")


async def shutdown() -> None:
    from db.pool import close_pool
    await close_pool()


async def get_pool():
    from db.pool import get_pool as _get_pool
    return await _get_pool()


async def verify_session(credentials: HTTPAuthorizationCredentials = Security(_security)):
    """로그인 세션 토큰(Bearer)을 검증하고 사용자명을 반환한다."""
    from api.auth import session_user
    pool = await get_pool()
    user = await session_user(pool, credentials.credentials)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="인증이 필요합니다. 로그인하세요.",
        )
    return user
