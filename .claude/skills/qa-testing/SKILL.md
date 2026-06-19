---
name: qa-testing
description: |
  Python 코드의 QA 검증을 수행하는 스킬. ruff 린트, pytest 단위 테스트, TimescaleDB·Prometheus·Loki 통합 테스트, 커버리지 80% 체크를 실행한다. 'QA 실행', '테스트 작성', '린트 검사', '커버리지 확인', '코드 품질 검증', '통합 테스트 추가', 'pytest 설정', 'CI 테스트 구성' 등 테스트·검증 관련 요청 시 반드시 이 스킬을 사용할 것.
---

# QA Testing 스킬

## 검증 레이어

| 레이어 | 도구 | CI 블로킹 여부 |
|--------|------|--------------|
| L1: 린트 | ruff | 블로킹 |
| L2: 단위 테스트 + 커버리지 | pytest + pytest-cov | 커버리지 80% 미만 시 블로킹 |
| L3: 통합 테스트 | pytest -m integration | 경고만 (인프라 문제 가능) |

---

## L1: ruff 린트

```bash
# 자동 수정 가능한 항목 수정
ruff check src/ --select E,F,W,I --fix
# 포맷 체크 (수정 없이)
ruff format src/ --check
```

ruff는 flake8 + isort + pyupgrade를 통합한다. `--fix`로 import 정렬, 불필요한 공백 등을 자동 수정한다.

---

## L2: 단위 테스트 패턴

외부 의존성(Prometheus, Loki, TimescaleDB, K8s API)을 mock으로 대체한다.

```python
# tests/unit/test_os_collector.py
import pytest
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_prometheus_query_maps_node_correctly():
    fake_response = {
        "data": {"result": [
            {"metric": {"instance": "192.168.78.101:9100"}, "value": [0, "45.2"]}
        ]}
    }
    with patch("httpx.AsyncClient.get", return_value=AsyncMock(json=lambda: fake_response)):
        from collector.os_collector import PrometheusCollector
        collector = PrometheusCollector()
        result = await collector.query_cpu_usage()
        assert result["playcekubewrk01"]["cpu_usage_ratio"] == pytest.approx(45.2)

@pytest.mark.asyncio
async def test_threshold_check_triggers_alert():
    from collector.os_service import check_and_alert
    alerts = check_and_alert({"node": "wrk01", "cpu_usage_ratio": 92.0})
    assert len(alerts) == 1
    assert alerts[0]["crisis_type"] == "HIGH_CPU"
    assert alerts[0]["severity"] == "critical"

# tests/unit/test_predictor.py
def test_linear_regression_increasing_trend():
    from analysis.predictor import TrendPredictor
    predictor = TrendPredictor()
    # 14일 데이터: 50%에서 70%로 증가
    data = [{"value": 50 + i * (20 / 13), "timestamp": i} for i in range(14)]
    result = predictor.predict_metric(data, horizon_days=30)
    assert result["trend"] == "increasing"
    assert result["forecast_30d"] > 70
    assert result["confidence"] in ("high", "medium")

# tests/unit/test_crisis_catalog.py
def test_crisis_catalog_has_all_types():
    from analysis.crisis_catalog import CRISIS_CATALOG
    expected = {"HIGH_CPU", "MEMORY_EXHAUSTION", "DISK_FULL", "HIGH_LOAD",
                "CRASHLOOP_BACKOFF", "NODE_NOT_READY", "OOM_KILLED"}
    assert set(CRISIS_CATALOG.keys()) == expected
    for crisis_type, data in CRISIS_CATALOG.items():
        assert "description" in data
        assert "immediate_actions" in data
        assert "references" in data
        assert len(data["references"]) >= 1

# tests/unit/test_api.py
from fastapi.testclient import TestClient

def test_health_endpoint():
    from api.main import app
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

def test_metrics_requires_auth():
    from api.main import app
    client = TestClient(app)
    resp = client.get("/api/v1/metrics/summary/playce-k8s")
    assert resp.status_code == 401
```

---

## L3: 통합 테스트 패턴

실제 클러스터 서비스에 연결한다. CI에서는 K8s self-hosted runner가 클러스터 내부에서 실행되므로 서비스 DNS가 동작한다.

```python
# tests/integration/test_prometheus.py
import pytest, httpx

PROMETHEUS = "http://prometheus-stack-kube-prom-prometheus.monitoring:9090"
LOKI = "http://loki-stack.logging:3100"

@pytest.mark.integration
@pytest.mark.asyncio
async def test_prometheus_reachable():
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{PROMETHEUS}/-/ready")
    assert resp.status_code == 200

@pytest.mark.integration
@pytest.mark.asyncio
async def test_node_exporter_has_8_nodes():
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{PROMETHEUS}/api/v1/query", params={"query": "node_load1"})
    data = resp.json()
    assert data["status"] == "success"
    assert len(data["data"]["result"]) == 8

@pytest.mark.integration
@pytest.mark.asyncio
async def test_loki_reachable():
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{LOKI}/ready")
    assert resp.status_code == 200

# tests/integration/test_timescaledb.py
@pytest.mark.integration
@pytest.mark.asyncio
async def test_timescaledb_insert_and_query():
    import asyncpg, os
    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"])
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO os_metrics(time, cluster_name, node_name, cpu_usage_ratio)
            VALUES (NOW(), 'test-cluster', 'test-node-qa', 42.5)
        """)
        row = await conn.fetchrow(
            "SELECT cpu_usage_ratio FROM os_metrics WHERE node_name = 'test-node-qa' ORDER BY time DESC LIMIT 1"
        )
        assert row["cpu_usage_ratio"] == pytest.approx(42.5)
        # 테스트 데이터 정리
        await conn.execute("DELETE FROM os_metrics WHERE node_name = 'test-node-qa'")
    await pool.close()
```

---

## pytest 설정 파일

```ini
# pytest.ini
[pytest]
asyncio_mode = auto
markers =
    unit: 단위 테스트 (mock 사용)
    integration: 통합 테스트 (실제 서비스)
testpaths = tests
addopts = --tb=short -q
```

```ini
# .coveragerc
[coverage:run]
source = src/
omit = tests/*, */__init__.py

[coverage:report]
fail_under = 80
show_missing = true
```

---

## Makefile 타깃

```makefile
lint:
	ruff check src/ --select E,F,W,I --fix
	ruff format src/ --check

test-unit:
	pytest tests/unit/ -v --cov=src/ --cov-report=term-missing --cov-fail-under=80

test-integration:
	pytest tests/integration/ -m integration -v

qa: lint test-unit
	@echo "QA PASSED"
```

---

## QA 결과 리포트 구조

```json
{
  "qa_run_id": "qa-20260620-001",
  "git_sha": "abc1234",
  "lint": {"status": "pass", "violations": 0},
  "unit_tests": {"status": "pass", "total": 45, "passed": 45, "coverage": 83.5},
  "integration_tests": {"status": "pass", "total": 12, "passed": 12},
  "overall": "pass"
}
```

## 원칙

- 커버리지 80% 미만: CI 빌드 차단
- 통합 테스트 실패: 경고만 (인프라 문제와 코드 문제 구분)
- 테스트 데이터: `test-` 접두사 사용, 완료 후 반드시 정리
