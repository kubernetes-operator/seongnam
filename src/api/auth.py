"""사용자명+비밀번호 인증 — PBKDF2 해시 + 세션 토큰(TimescaleDB 저장).

- 비밀번호는 PBKDF2-HMAC-SHA256 + per-user 랜덤 salt 로만 저장(평문 없음).
- 세션은 서버측 opaque 토큰(sessions 테이블). 로그인 시 발급되어 Bearer 로 전달되고,
  로그아웃/비밀번호 변경 시 무효화된다.
- 최초 기동 시 기본 관리자(admin/password)를 시드한다 — **반드시 즉시 변경할 것**.
  기본 자격증명은 ADMIN_USERNAME/ADMIN_PASSWORD 환경변수로 재정의 가능.
"""
import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status

_PBKDF2_ITER = 390_000
MIN_PASSWORD_LEN = 8
SESSION_TTL = timedelta(days=7)

DEFAULT_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
DEFAULT_PASSWORD = os.getenv("ADMIN_PASSWORD", "password")  # 약한 기본값 — 즉시 변경


def _hash(password: str, salt_hex: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), _PBKDF2_ITER).hex()


async def ensure_seed(pool) -> None:
    """users 테이블이 비어 있으면 기본 관리자 시드(멱등)."""
    async with pool.acquire() as conn:
        n = await conn.fetchval("SELECT count(*) FROM users")
        if n and n > 0:
            return
        salt = secrets.token_bytes(16).hex()
        await conn.execute(
            "INSERT INTO users (username, password_hash, salt) VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
            DEFAULT_USERNAME, _hash(DEFAULT_PASSWORD, salt), salt,
        )


async def verify_user(pool, username: str, password: str) -> bool:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT password_hash, salt FROM users WHERE username = $1", username)
    if not row:
        _hash(password, "00" * 16)  # 사용자명 열거 타이밍 side-channel 완화
        return False
    return secrets.compare_digest(_hash(password, row["salt"]), row["password_hash"])


async def create_session(pool, username: str) -> str:
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + SESSION_TTL
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO sessions (token, username, expires_at) VALUES ($1, $2, $3)",
            token, username, expires,
        )
    return token


async def session_user(pool, token: str):
    """유효한 세션이면 username, 아니면 None."""
    if not token:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT username, expires_at FROM sessions WHERE token = $1", token)
    if not row:
        return None
    if row["expires_at"] < datetime.now(timezone.utc):
        await delete_session(pool, token)
        return None
    return row["username"]


async def delete_session(pool, token: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM sessions WHERE token = $1", token)


async def change_password(pool, username: str, current: str, new: str) -> None:
    if not await verify_user(pool, username, current):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="현재 비밀번호가 올바르지 않습니다")
    if len(new) < MIN_PASSWORD_LEN:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"비밀번호는 {MIN_PASSWORD_LEN}자 이상이어야 합니다")
    salt = secrets.token_bytes(16).hex()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET password_hash = $1, salt = $2 WHERE username = $3",
                           _hash(new, salt), salt, username)
        # 비밀번호 변경 시 기존 세션 전부 무효화
        await conn.execute("DELETE FROM sessions WHERE username = $1", username)
