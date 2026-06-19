"""TimescaleDB 통합 테스트 — 실제 DB 필요 (CI에서 skip 가능)."""
import pytest
import asyncio
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../src'))

pytestmark = pytest.mark.skipif(
    not os.getenv("INTEGRATION_TEST"),
    reason="INTEGRATION_TEST 환경변수 미설정 시 건너뜀",
)


@pytest.mark.asyncio
async def test_db_connection():
    from db.pool import get_pool, close_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.fetchval("SELECT 1")
    assert result == 1
    await close_pool()


@pytest.mark.asyncio
async def test_schema_tables_exist():
    from db.pool import get_pool, close_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        tables = [r["tablename"] for r in await conn.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        )]
    expected = ["cluster_nodes", "os_metrics", "k8s_metrics", "events", "reports"]
    for t in expected:
        assert t in tables, f"테이블 누락: {t}"
    await close_pool()


@pytest.mark.asyncio
async def test_insert_and_query_os_metrics():
    from db.pool import get_pool, close_pool
    from db.queries import upsert_cluster_node, insert_os_metrics, query_latest_metrics
    pool = await get_pool()
    await upsert_cluster_node(pool, "test-cluster", "test-node", "127.0.0.1")
    record = {
        "cluster_name": "test-cluster",
        "node_name": "test-node",
        "cpu": {"cpu_usage_ratio": 55.0, "load1": 1.2, "load5": 1.0, "load15": 0.9, "load_per_core": 1.1},
        "memory": {"memory_usage_ratio": 60.0, "memory_used_bytes": 1073741824, "memory_total_bytes": 4294967296},
        "disk": {"disk_usage_ratio": 40.0, "disk_used_bytes": 10737418240, "disk_total_bytes": 107374182400},
        "network": {"network_tx_bytes": 1000000, "network_rx_bytes": 2000000},
    }
    await insert_os_metrics(pool, [record])
    latest = await query_latest_metrics(pool, "test-cluster")
    assert "test-node" in latest
    assert abs(latest["test-node"]["cpu_usage_ratio"] - 55.0) < 1.0
    await close_pool()
