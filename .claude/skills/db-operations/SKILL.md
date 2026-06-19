---
name: db-operations
description: |
  TimescaleDB(PostgreSQL) 스키마 생성, 메트릭 데이터 배치 삽입, 시계열 집계 쿼리, 연속 집계(Continuous Aggregate), 데이터 보존 정책을 Python asyncpg로 구현한다. 'TimescaleDB', 'DB 적재', '메트릭 저장', '시계열 쿼리', 'asyncpg', '집계 쿼리' 관련 구현 시 반드시 이 스킬을 사용할 것.
---

# DB Operations 스킬

## 스키마 초기화

```python
# schema.py
SCHEMA_SQL = """
-- 확장 활성화
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- 클러스터/노드 레지스트리
CREATE TABLE IF NOT EXISTS cluster_nodes (
    id          SERIAL PRIMARY KEY,
    cluster_name TEXT NOT NULL,
    node_name    TEXT NOT NULL,
    node_ip      TEXT,
    os_distro    TEXT,
    kernel_version TEXT,
    cpu_cores    INTEGER,
    memory_total_bytes BIGINT,
    registered_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(cluster_name, node_name)
);

-- OS 메트릭 (hypertable)
CREATE TABLE IF NOT EXISTS os_metrics (
    time                  TIMESTAMPTZ NOT NULL,
    cluster_name          TEXT NOT NULL,
    node_name             TEXT NOT NULL,
    cpu_usage_ratio       DOUBLE PRECISION,
    cpu_iowait_percent    DOUBLE PRECISION,
    memory_usage_ratio    DOUBLE PRECISION,
    memory_used_bytes     BIGINT,
    swap_usage_ratio      DOUBLE PRECISION,
    load1                 DOUBLE PRECISION,
    load5                 DOUBLE PRECISION,
    load15                DOUBLE PRECISION,
    load_per_core         DOUBLE PRECISION,
    disk_usage_ratio      DOUBLE PRECISION,
    disk_read_bytes_per_sec  BIGINT,
    disk_write_bytes_per_sec BIGINT,
    net_rx_bytes_per_sec  BIGINT,
    net_tx_bytes_per_sec  BIGINT,
    processes_running     INTEGER,
    processes_zombie      INTEGER
);
SELECT create_hypertable('os_metrics', 'time', if_not_exists => TRUE);

-- K8s 메트릭 (hypertable)
CREATE TABLE IF NOT EXISTS k8s_metrics (
    time                      TIMESTAMPTZ NOT NULL,
    cluster_name              TEXT NOT NULL,
    node_name                 TEXT NOT NULL,
    node_status               TEXT,
    cpu_allocatable           DOUBLE PRECISION,
    cpu_requested             DOUBLE PRECISION,
    cpu_used                  DOUBLE PRECISION,
    cpu_request_ratio         DOUBLE PRECISION,
    cpu_usage_ratio           DOUBLE PRECISION,
    memory_allocatable_bytes  BIGINT,
    memory_requested_bytes    BIGINT,
    memory_used_bytes         BIGINT,
    memory_request_ratio      DOUBLE PRECISION,
    memory_usage_ratio        DOUBLE PRECISION,
    pods_running              INTEGER,
    pods_pending              INTEGER,
    pods_failed               INTEGER,
    pods_crash_loop           INTEGER,
    actual_usage_available    BOOLEAN DEFAULT FALSE
);
SELECT create_hypertable('k8s_metrics', 'time', if_not_exists => TRUE);

-- 이벤트/알림
CREATE TABLE IF NOT EXISTS events (
    id           SERIAL PRIMARY KEY,
    time         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    cluster_name TEXT NOT NULL,
    node_name    TEXT,
    event_type   TEXT NOT NULL,
    severity     TEXT NOT NULL,
    message      TEXT NOT NULL,
    details      JSONB,
    resolved     BOOLEAN DEFAULT FALSE,
    resolved_at  TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_events_cluster_time ON events(cluster_name, time DESC);
CREATE INDEX IF NOT EXISTS idx_events_severity ON events(severity) WHERE NOT resolved;

-- 리포트 이력
CREATE TABLE IF NOT EXISTS reports (
    id           SERIAL PRIMARY KEY,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    report_type  TEXT NOT NULL,
    cluster_name TEXT,
    period_start TIMESTAMPTZ NOT NULL,
    period_end   TIMESTAMPTZ NOT NULL,
    format       TEXT NOT NULL,
    file_path    TEXT,
    summary      JSONB
);
"""

# 연속 집계 (1시간 단위)
CONTINUOUS_AGGREGATE_SQL = """
CREATE MATERIALIZED VIEW IF NOT EXISTS os_metrics_hourly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', time) AS bucket,
    cluster_name,
    node_name,
    avg(cpu_usage_ratio)    AS cpu_avg,
    max(cpu_usage_ratio)    AS cpu_max,
    min(cpu_usage_ratio)    AS cpu_min,
    avg(memory_usage_ratio) AS mem_avg,
    max(memory_usage_ratio) AS mem_max,
    avg(disk_usage_ratio)   AS disk_avg,
    max(disk_usage_ratio)   AS disk_max,
    avg(load1)              AS load_avg,
    max(load1)              AS load_max
FROM os_metrics
GROUP BY bucket, cluster_name, node_name
WITH NO DATA;

SELECT add_continuous_aggregate_policy('os_metrics_hourly',
    start_offset => INTERVAL '3 hours',
    end_offset   => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE
);

-- 데이터 보존 정책
SELECT add_retention_policy('os_metrics', INTERVAL '90 days', if_not_exists => TRUE);
"""
```

## 데이터베이스 풀 관리

```python
import asyncpg
import os
from contextlib import asynccontextmanager

_pool: asyncpg.Pool = None

async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            dsn=os.environ["DATABASE_URL"],
            min_size=5,
            max_size=20,
            command_timeout=30,
        )
    return _pool

@asynccontextmanager
async def db_conn():
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn
```

## 배치 삽입 패턴

```python
async def insert_os_metrics(records: list[dict]) -> int:
    """OS 메트릭을 배치로 삽입한다. 개별 INSERT 대신 COPY를 사용한다."""
    if not records:
        return 0

    columns = [
        "time", "cluster_name", "node_name",
        "cpu_usage_ratio", "cpu_iowait_percent",
        "memory_usage_ratio", "memory_used_bytes", "swap_usage_ratio",
        "load1", "load5", "load15", "load_per_core",
        "disk_usage_ratio",
        "net_rx_bytes_per_sec", "net_tx_bytes_per_sec",
        "processes_running", "processes_zombie",
    ]

    rows = [
        (
            r["collected_at"],
            r["cluster_name"],
            r["node_name"],
            r.get("cpu", {}).get("usage_ratio"),
            r.get("cpu", {}).get("iowait_percent"),
            r.get("memory", {}).get("usage_ratio"),
            r.get("memory", {}).get("used_bytes"),
            r.get("memory", {}).get("swap_usage_ratio"),
            r.get("load", {}).get("load1"),
            r.get("load", {}).get("load5"),
            r.get("load", {}).get("load15"),
            r.get("load", {}).get("load_per_core"),
            # disk: / 파티션 사용률만 대표값으로 사용
            next((d["usage_ratio"] for d in r.get("disk", []) if d["mount"] == "/"), None),
            r.get("network", {}).get("interfaces", [{}])[0].get("rx_bytes", 0),
            r.get("network", {}).get("interfaces", [{}])[0].get("tx_bytes", 0),
            r.get("load", {}).get("processes_running"),
            r.get("load", {}).get("processes_zombie"),
        )
        for r in records
    ]

    async with db_conn() as conn:
        result = await conn.copy_records_to_table(
            "os_metrics", records=rows, columns=columns
        )
    return len(rows)
```

## 집계 쿼리 패턴

```python
async def query_metric_timeseries(
    cluster_name: str,
    node_name: str,
    metric: str,
    start: str,
    end: str,
    interval: str = "1h",
) -> list[dict]:
    """
    시계열 메트릭을 지정 간격으로 집계하여 반환한다.
    interval: '1m', '1h', '1d', '7d' 등 TimescaleDB time_bucket 형식.
    """
    # 간격에 따라 원본 테이블 또는 집계 뷰 선택
    if interval in ("1h", "2h", "6h"):
        table = "os_metrics_hourly"
        time_col = "bucket"
    else:
        table = "os_metrics"
        time_col = "time"

    sql = f"""
        SELECT
            time_bucket($1::interval, {time_col}) AS bucket,
            avg({metric}) AS avg_value,
            max({metric}) AS max_value,
            min({metric}) AS min_value
        FROM {table}
        WHERE cluster_name = $2
          AND node_name = $3
          AND {time_col} BETWEEN $4::timestamptz AND $5::timestamptz
        GROUP BY bucket
        ORDER BY bucket ASC
    """

    async with db_conn() as conn:
        rows = await conn.fetch(sql, interval, cluster_name, node_name, start, end)

    return [
        {
            "time": row["bucket"].isoformat(),
            "avg": round(row["avg_value"] or 0, 2),
            "max": round(row["max_value"] or 0, 2),
            "min": round(row["min_value"] or 0, 2),
        }
        for row in rows
    ]

async def query_top_nodes(
    cluster_name: str,
    metric: str,
    limit: int = 5,
    period_hours: int = 24,
) -> list[dict]:
    """최근 N시간 동안 지정 메트릭 평균이 높은 상위 노드를 반환한다."""
    sql = f"""
        SELECT
            node_name,
            avg({metric}) AS avg_value,
            max({metric}) AS max_value
        FROM os_metrics
        WHERE cluster_name = $1
          AND time > NOW() - ($2 || ' hours')::interval
        GROUP BY node_name
        ORDER BY avg_value DESC
        LIMIT $3
    """
    async with db_conn() as conn:
        rows = await conn.fetch(sql, cluster_name, str(period_hours), limit)
    return [dict(row) for row in rows]
```

## 환경변수

```
DATABASE_URL=postgresql://user:pass@timescaledb:5432/k8s_monitor
```

## 의존성

```
asyncpg>=0.29.0
```
