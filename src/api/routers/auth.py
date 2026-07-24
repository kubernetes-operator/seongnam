"""로그인/로그아웃/비밀번호 변경 엔드포인트 (사용자명+비밀번호 인증)."""
from fastapi import APIRouter, Depends, HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

from api.dependencies import get_pool, verify_session
from api.models import ApiResponse

router = APIRouter()
_bearer = HTTPBearer(auto_error=False)


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/login")
async def login(body: LoginRequest, pool=Depends(get_pool)):
    from api.auth import verify_user, create_session
    if not await verify_user(pool, body.username, body.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="사용자명 또는 비밀번호가 올바르지 않습니다")
    token = await create_session(pool, body.username)
    return ApiResponse.ok({"token": token, "username": body.username})


@router.post("/logout")
async def logout(credentials: HTTPAuthorizationCredentials = Security(_bearer), pool=Depends(get_pool)):
    from api.auth import delete_session
    if credentials and credentials.credentials:
        await delete_session(pool, credentials.credentials)
    return ApiResponse.ok({"logged_out": True})


@router.get("/me")
async def me(user=Depends(verify_session)):
    return ApiResponse.ok({"username": user})


@router.post("/change-password")
async def change_pw(body: ChangePasswordRequest, user=Depends(verify_session), pool=Depends(get_pool)):
    from api.auth import change_password
    await change_password(pool, user, body.current_password, body.new_password)
    return ApiResponse.ok({"changed": True})
