"""Prometheus 통합 테스트 — 실제 Prometheus 필요 (CI에서 skip 가능)."""
import pytest
import asyncio
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../src'))

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://prometheus-stack-kube-prom-prometheus.monitoring:9090")

pytestmark = pytest.mark.skipif(
    not os.getenv("INTEGRATION_TEST"),
    reason="INTEGRATION_TEST 환경변수 미설정 시 건너뜀",
)


@pytest.mark.asyncio
async def test_prometheus_reachable():
    from collector.os_collector import PrometheusCollector
    col = PrometheusCollector()
    result = await col.query("up")
    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_prometheus_cpu_query():
    from collector.os_collector import PrometheusCollector
    col = PrometheusCollector()
    result = await col.query('100 - (avg by(instance) (rate(node_cpu_seconds_total{mode="idle"}[5m]))) * 100')
    assert isinstance(result, dict)
    assert len(result) > 0
