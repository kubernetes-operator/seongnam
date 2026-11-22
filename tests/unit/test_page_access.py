"""실제 PostgreSQL의 격리된 임시 스키마만 사용하는 권한 회귀 테스트."""
import asyncio
import os
import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch
import asyncpg
import pytest
from fastapi import FastAPI, Depends, HTTPException
from httpx import AsyncClient, ASGITransport
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from api import access, auth
from api.dependencies import verify_session
from api.routers.auth import router

@pytest.fixture
async def db(monkeypatch):
    dsn=os.environ.get('WS_TEST_POSTGRES_DSN')
    if not dsn: pytest.skip('WS_TEST_POSTGRES_DSN must point to the disposable test PostgreSQL')
    # 이 테스트 전용 값만 허용하여 실수로 기존 DB에 연결하지 않는다.
    if not dsn.startswith('postgresql://ws_test:ws_test_fixture@127.0.0.1:') or not dsn.endswith('/ws_test'):
        raise RuntimeError('Only the disposable localhost test database is permitted')
    conn=await asyncpg.connect(dsn)
    schema='ws_test_'+uuid.uuid4().hex
    await conn.execute('CREATE SCHEMA '+schema)
    pool=await asyncpg.create_pool(dsn,min_size=1,max_size=4,server_settings={'search_path':schema})
    monkeypatch.setattr(auth,'_PBKDF2_ITER',1000)
    async with pool.acquire() as c:
        await c.execute("CREATE TABLE users(username TEXT PRIMARY KEY,password_hash TEXT NOT NULL,salt TEXT NOT NULL); CREATE TABLE sessions(token TEXT PRIMARY KEY,username TEXT REFERENCES users(username) ON DELETE CASCADE,expires_at TIMESTAMPTZ NOT NULL)")
        await c.execute('INSERT INTO users VALUES($1,$2,$3)','existing-admin',auth._hash('existing-test-password','11'*16),'11'*16)
    await access.migrate(pool)
    try: yield pool
    finally:
        await pool.close()
        await conn.execute('DROP SCHEMA '+schema+' CASCADE')
        await conn.close()

@pytest.fixture
async def client(db):
    app=FastAPI()
    app.include_router(router,prefix='/api/v1/auth')
    @app.get('/api/v1/logs')
    async def logs(user=Depends(verify_session)): return {'ok':True}
    @app.patch('/api/v1/events/1/resolve')
    async def resolve(user=Depends(verify_session)): return {'ok':True}
    with patch('api.dependencies.get_pool',new=AsyncMock(return_value=db)):
        from api.dependencies import get_pool
        # dependency overrides use original function objects captured at import.
        from api.routers import auth as routes
        app.dependency_overrides[routes.get_pool]=lambda:db
        async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as c:
            yield c

async def headers(db,username='existing-admin'):
    return {'Authorization':'Bearer '+await auth.create_session(db,username)}

async def test_migration_preserves_native_account_and_hash(db):
    async with db.acquire() as c:
        before=await c.fetchrow('SELECT * FROM users WHERE username=$1','existing-admin')
    await access.migrate(db)
    await access.migrate(db)
    async with db.acquire() as c:
        assert dict(before)==dict(await c.fetchrow('SELECT * FROM users WHERE username=$1','existing-admin'))
    assert (await access.get_access(db,'existing-admin'))['role']=='admin'
    assert await auth.verify_user(db,'existing-admin','existing-test-password')

async def test_http_creation_grants_and_fresh_revocation(db,client):
    h=await headers(db)
    response=await client.post('/api/v1/auth/ui/users',headers=h,json={'username':'restricted','password':'test-password-123','pages':['logs']})
    assert response.status_code==200,response.text
    vh=await headers(db,'restricted')
    assert (await client.get('/api/v1/logs',headers=vh)).status_code==200
    assert (await client.get('/api/v1/auth/ui/users',headers=vh)).status_code==403
    assert (await client.post('/api/v1/auth/ui/users',headers=vh,json={'username':'bad','password':'test-password-123'})).status_code==403
    assert (await client.patch('/api/v1/events/1/resolve',headers=vh)).status_code==403
    response=await client.patch('/api/v1/auth/ui/users/restricted',headers=h,json={'pages':[]})
    assert response.status_code==200,response.text
    assert (await client.get('/api/v1/logs',headers=vh)).status_code==403
    own=await client.get('/api/v1/auth/ui/session',headers=vh)
    assert own.status_code==200
    assert own.json()['pages']==['settings']

async def test_confirmation_current_password_and_session_invalidation(db,client):
    h=await headers(db)
    url='/api/v1/auth/ui/password'
    body={'current_password':'existing-test-password','new_password':'changed-test-password','confirm_password':'different-test-password'}
    assert (await client.post(url,headers=h,json=body)).status_code==400
    body['confirm_password']=body['new_password'];body['current_password']='incorrect'
    assert (await client.post(url,headers=h,json=body)).status_code==401
    body['current_password']='existing-test-password'
    response=await client.post(url,headers=h,json=body)
    assert response.status_code==200,response.text
    assert response.json()['reauthenticate']
    assert await auth.verify_user(db,'existing-admin','changed-test-password')
    assert not await auth.verify_user(db,'existing-admin','existing-test-password')
    assert (await client.get('/api/v1/auth/me',headers=h)).status_code==401

async def test_invalid_grants_do_not_create_accounts(db,client):
    h=await headers(db)
    for payload in ({'username':'invalid/name','pages':[]},{'username':'invalid','pages':['unknown']},{'username':'invalid','pages':['users']}):
        r=await client.post('/api/v1/auth/ui/users',headers=h,json={**payload,'password':'test-password-123'})
        assert r.status_code==400,r.text
    assert [u['username'] for u in await access.users(db)]==['existing-admin']

async def test_concurrent_demotion_preserves_last_admin(db):
    await access.create(db,'second-admin','test-password-123','admin',[])
    results=await asyncio.gather(access.update(db,'existing-admin',{'role':'viewer','pages':[]}),access.update(db,'second-admin',{'role':'viewer','pages':[]}),return_exceptions=True)
    assert sum(isinstance(r,HTTPException) and r.status_code==409 for r in results)==1
    assert sum(u['role']=='admin' for u in await access.users(db))==1

async def test_concurrent_duplicate_creation_is_atomic(db):
    results=await asyncio.gather(*(access.create(db,'duplicate','test-password-123','viewer',['logs']) for _ in range(2)),return_exceptions=True)
    assert sum(isinstance(r,HTTPException) and r.status_code==409 for r in results)==1
    assert len([u for u in await access.users(db) if u['username']=='duplicate'])==1

@pytest.mark.parametrize('path,method', [('/api/v1/logs','GET'),('/api/v1/events/1/resolve','PATCH'),('/api/v1/auth/ui/users','GET'),('/api/v1/unknown','GET')])
def test_missing_or_malformed_metadata_fails_closed(path,method):
    for row in (None,{'role':'unknown','pages':[]},{'role':'viewer','pages':'malformed'}):
        with pytest.raises(HTTPException) as error: access.check_access(access.metadata(row),path,method)
        assert error.value.status_code==403
