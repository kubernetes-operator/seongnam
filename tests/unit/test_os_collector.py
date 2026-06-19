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
