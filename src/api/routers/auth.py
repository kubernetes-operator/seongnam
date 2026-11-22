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
async def me(user=Depends(verify_session), pool=Depends(get_pool)):
    from api.access import summary
    return ApiResponse.ok(await summary(pool,user))


@router.post("/change-password")
async def change_pw(body: ChangePasswordRequest, user=Depends(verify_session), pool=Depends(get_pool)):
    from api.auth import change_password
    await change_password(pool, user, body.current_password, body.new_password)
    return ApiResponse.ok({"changed": True})


class UIConfirmedPassword(BaseModel):
    current_password: str
    new_password: str
    confirm_password: str

class UICreateUser(BaseModel):
    username: str
    password: str
    role: str = 'viewer'
    pages: list[str] = []

class UIUpdateUser(BaseModel):
    role: str | None = None
    pages: list[str] | None = None
    password: str | None = None

@router.get('/ui/session')
async def ui_session(user=Depends(verify_session),pool=Depends(get_pool)):
    from api.access import summary
    return await summary(pool,user)

@router.post('/ui/password')
async def ui_password(body:UIConfirmedPassword,user=Depends(verify_session),pool=Depends(get_pool)):
    if body.new_password!=body.confirm_password:
        raise HTTPException(400,'새 비밀번호가 일치하지 않습니다')
    from api.auth import change_password
    await change_password(pool,user,body.current_password,body.new_password)
    return {'ok':True,'reauthenticate':True}

@router.get('/ui/users')
async def ui_users(user=Depends(verify_session),pool=Depends(get_pool)):
    from api.access import users
    return await users(pool)

@router.post('/ui/users')
async def ui_create_user(body:UICreateUser,user=Depends(verify_session),pool=Depends(get_pool)):
    from api.access import create
    return await create(pool,body.username,body.password,body.role,body.pages)

@router.patch('/ui/users/{username}')
async def ui_update_user(username:str,body:UIUpdateUser,user=Depends(verify_session),pool=Depends(get_pool)):
    from api.access import update
    changes=body.model_dump(exclude_unset=True)
    if any(value is None for value in changes.values()):
        raise HTTPException(400,'변경 값은 null일 수 없습니다')
    return await update(pool,username,changes)
