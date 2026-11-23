"""OS Collector 유닛 테스트 (Prometheus mock)."""
import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../src'))

from unittest.mock import AsyncMock, patch, MagicMock
from collector.os_collector import PrometheusCollector, NODE_MAP


FAKE_VECTOR = {
    "status": "success",
    "data": {
        "resultType": "vector",
        "result": [
            {"metric": {"instance": "192.168.77.101:9100"}, "value": [0, "55.3"]},
        ],
    },
}


@pytest.mark.asyncio
async def test_query_returns_float():
    collector = PrometheusCollector()

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value=FAKE_VECTOR)

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await collector.query("up")

    # query()는 raw instance 키(IP:port)를 반환; NODE_MAP 매핑은 collect_all()에서 함
    assert "192.168.77.101:9100" in result
    assert abs(result["192.168.77.101:9100"] - 55.3) < 0.01


def test_node_map_coverage():
    assert len(NODE_MAP) >= 8


def test_node_map_values_are_strings():
    for k, v in NODE_MAP.items():
        assert isinstance(k, str) and ":" in k, f"잘못된 키: {k}"
        assert isinstance(v, str), f"값이 문자열 아님: {v}"


def _vec(pairs):
    return {"status": "success", "data": {"resultType": "vector", "result": [
        {"metric": {"instance": i}, "value": [0, str(v)]} for i, v in pairs]}}


@pytest.mark.asyncio
async def test_collect_all_uses_prometheus_for_former_ssh_fields():
    """SSH 없이 코어 수·inode·uptime·프로세스 수를 Prometheus 에서 채운다."""
    inst = "192.168.77.101:9100"
    collector = PrometheusCollector()

    async def fake_query(promql):
        if "node_cpu_seconds_total{mode=\"idle\"}" in promql and promql.startswith("count"):
            return {inst: 4.0}
        if promql == "node_load1":
            return {inst: 2.0}
        if "node_filesystem_files_free" in promql:
            return {inst: 12.345}
        if "node_boot_time_seconds" in promql:
            return {inst: 3600.0}
        if promql == "node_procs_running":
            return {inst: 3.0}
        if "node_processes_state" in promql:
            return {}  # processes 수집기 꺼짐
        return {inst: 1.0}

    collector.query = fake_query
    collector.query_label = AsyncMock(return_value={})
    data = await collector.collect_all("c")
    nm = next(n for n in data["node_metrics"] if n["node_name"] == NODE_MAP[inst])

    assert nm["cpu"]["cores"] == 4
    assert nm["load"]["load_per_core"] == 0.5
    assert nm["disk"]["inode_usage_ratio"] == 12.35
    assert nm["uptime_sec"] == 3600
    assert nm["load"]["processes_running"] == 3
    # 지표가 없으면 0 이 아니라 None (오인 표시 방지)
    assert nm["load"]["processes_zombie"] is None
    # 다른 노드는 지표가 없어도 실패하지 않는다
    other = next(n for n in data["node_metrics"] if n["node_name"] != NODE_MAP[inst])
    assert other["cpu"]["cores"] is None
