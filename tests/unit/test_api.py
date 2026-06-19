"""API 엔드포인트 유닛 테스트 (DB mock)."""
import os
import sys
import pytest

os.environ.setdefault("API_KEY", "test-key")
os.environ.setdefault("DATABASE_URL", "postgresql://x:x@localhost/x")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../src'))

from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient, ASGITransport


def _make_mock_pool():
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[])
    mock_conn.fetchrow = AsyncMock(return_value=None)
    mock_conn.fetchval = AsyncMock(return_value=1)

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=mock_ctx)
    return pool


@pytest.fixture
def mock_pool():
    return _make_mock_pool()


@pytest.fixture
def app(mock_pool):
    # 패치 전에 서브모듈을 명시적으로 import해야 patch()가 동작함
    import db.pool    # noqa: F401
    import db.schema  # noqa: F401
    with patch("db.pool.get_pool", new=AsyncMock(return_value=mock_pool)), \
         patch("db.pool.close_pool", new=AsyncMock()), \
         patch("db.schema.init_schema", new=AsyncMock()):
        from api.main import app as _app
        yield _app


@pytest.mark.asyncio
async def test_health(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/healthz")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_clusters_requires_auth(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/v1/clusters")
    # HTTPBearer: 토큰 없으면 403, 잘못된 토큰이면 401
    assert res.status_code in (401, 403)


@pytest.mark.asyncio
async def test_clusters_with_auth(app, mock_pool):
    with patch("db.queries.query_clusters", new=AsyncMock(return_value=[])):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test",
                               headers={"Authorization": "Bearer test-key"}) as client:
            res = await client.get("/api/v1/clusters")
    assert res.status_code == 200
    # ApiResponse 구조: {"status": "success", "data": [...]}
    assert res.json()["status"] == "success"
