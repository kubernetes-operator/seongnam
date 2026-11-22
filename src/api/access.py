"""웹 계정·페이지 권한. 기존 users/sessions와 독립적인 부가 메타데이터."""
import json
import secrets
from fastapi import HTTPException
from api import page_policy

PROJECT = 'seongnam'
SCHEMA = """
CREATE TABLE IF NOT EXISTS user_access (
 username TEXT PRIMARY KEY REFERENCES users(username) ON DELETE CASCADE,
 role TEXT NOT NULL CHECK (role IN ('admin','viewer')),
 pages JSONB
);
INSERT INTO user_access (username,role,pages)
 SELECT username,'admin',NULL FROM users ON CONFLICT DO NOTHING;
"""

async def migrate(pool):
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(SCHEMA)


def metadata(row):
    if not row:
        return {'role':'viewer','pages':[]}
    try:
        pages = row['pages']
        if isinstance(pages,str): pages=json.loads(pages)
        role=row['role']
        return {'role':role,'pages':page_policy.normalize(PROJECT,role,pages)}
    except (ValueError,TypeError,KeyError):
        return {'role':'viewer','pages':[]}

async def get_access(pool,username):
    async with pool.acquire() as conn:
        row=await conn.fetchrow('SELECT role,pages FROM user_access WHERE username=$1',username)
    return metadata(row)


def required_pages(path):
    # 여러 화면이 공유하는 조회 API는 그 데이터를 사용하는 페이지 중 하나를 허용한다.
    if path.startswith('/api/v1/auth/'):
        return ['users'] if '/users' in path else ['settings']
    if path.startswith('/api/v1/clusters'):
        return ['dashboard','nodes','events','predictions','reports']
    if path.startswith('/api/v1/metrics'):
        return ['dashboard','nodes']
    if path.startswith('/api/v1/events'):
        return ['dashboard','events']
    for page in ('logs','predictions','reports'):
        if path.startswith('/api/v1/'+page): return [page]
    return []


def check_access(access,path,method):
    pages=required_pages(path)
    if not any(page_policy.allowed(PROJECT,access['role'],access['pages'],p) for p in pages):
        raise HTTPException(403,'이 페이지에 접근할 권한이 없습니다')
    own=path in ('/api/v1/auth/logout','/api/v1/auth/change-password','/api/v1/auth/ui/password')
    if access['role']!='admin' and method not in ('GET','HEAD','OPTIONS') and not own:
        raise HTTPException(403,'관리자 권한이 필요합니다')

async def summary(pool,username):
    access=await get_access(pool,username)
    return {'username':username,'role':access['role'],
            'pages':page_policy.effective(PROJECT,access['role'],access['pages']),
            'availablePages':page_policy.PAGES[PROJECT],
            'canManageUsers':access['role']=='admin','passwordMinLength':8}

async def users(pool):
    async with pool.acquire() as conn:
        rows=await conn.fetch('SELECT u.username,a.role,a.pages FROM users u LEFT JOIN user_access a USING(username) ORDER BY u.username')
    return [{'username':r['username'],**metadata(r)} for r in rows]

async def create(pool,username,password,role,pages):
    from api.auth import _hash,MIN_PASSWORD_LEN
    try:
        username=page_policy.normalize_username(username)
        pages=page_policy.normalize(PROJECT,role,pages)
    except ValueError as error:
        raise HTTPException(400,str(error)) from error
    if len(password)<MIN_PASSWORD_LEN:
        raise HTTPException(400,'비밀번호는 8자 이상이어야 합니다')
    salt=secrets.token_bytes(16).hex()
    digest=_hash(password,salt)
    async with pool.acquire() as conn:
        async with conn.transaction():
            result=await conn.fetchval('INSERT INTO users(username,password_hash,salt) VALUES($1,$2,$3) ON CONFLICT DO NOTHING RETURNING username',username,digest,salt)
            if result is None: raise HTTPException(409,'이미 존재하는 사용자입니다')
            await conn.execute('INSERT INTO user_access(username,role,pages) VALUES($1,$2,$3::jsonb)',username,role,json.dumps(pages))
    return {'username':username,'role':role,'pages':pages}

async def update(pool,username,changes):
    from api.auth import _hash,MIN_PASSWORD_LEN
    # 모든 관리자 변경을 직렬화하여 동시 강등으로 마지막 관리자를 잃지 않는다.
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute('LOCK TABLE user_access IN EXCLUSIVE MODE')
            target=await conn.fetchrow('SELECT u.username,a.role,a.pages FROM users u LEFT JOIN user_access a USING(username) WHERE u.username=$1',username)
            if not target: raise HTTPException(404,'사용자가 없습니다')
            current=metadata(target)
            role=changes.get('role',current['role'])
            pages=changes.get('pages',current['pages'])
            try: pages=page_policy.normalize(PROJECT,role,pages)
            except ValueError as error: raise HTTPException(400,str(error)) from error
            if current['role']=='admin' and role!='admin':
                count=await conn.fetchval("SELECT count(*) FROM user_access WHERE role='admin'")
                if count<=1: raise HTTPException(409,'마지막 관리자는 강등할 수 없습니다')
            password=changes.get('password')
            if password is not None:
                if len(password)<MIN_PASSWORD_LEN: raise HTTPException(400,'비밀번호는 8자 이상이어야 합니다')
                salt=secrets.token_bytes(16).hex()
                await conn.execute('UPDATE users SET password_hash=$1,salt=$2 WHERE username=$3',_hash(password,salt),salt,username)
                await conn.execute('DELETE FROM sessions WHERE username=$1',username)
            await conn.execute('INSERT INTO user_access(username,role,pages) VALUES($1,$2,$3::jsonb) ON CONFLICT(username) DO UPDATE SET role=EXCLUDED.role,pages=EXCLUDED.pages',username,role,json.dumps(pages))
    return {'username':username,'role':role,'pages':pages}
