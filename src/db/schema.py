"""TimescaleDB 스키마 초기화."""

SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS cluster_nodes (
    id                 SERIAL PRIMARY KEY,
    cluster_name       TEXT NOT NULL,
    node_name          TEXT NOT NULL,
    node_ip            TEXT,
    os_distro          TEXT,
    kernel_version     TEXT,
    cpu_cores          INTEGER,
    memory_total_bytes BIGINT,
    registered_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at         TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(cluster_name, node_name)
);

CREATE TABLE IF NOT EXISTS os_metrics (
    time                     TIMESTAMPTZ NOT NULL,
    cluster_name             TEXT NOT NULL,
    node_name                TEXT NOT NULL,
    cpu_usage_ratio          DOUBLE PRECISION,
    cpu_iowait_percent       DOUBLE PRECISION,
    memory_usage_ratio       DOUBLE PRECISION,
    memory_used_bytes        BIGINT,
    swap_usage_ratio         DOUBLE PRECISION,
    load1                    DOUBLE PRECISION,
    load5                    DOUBLE PRECISION,
    load15                   DOUBLE PRECISION,
    load_per_core            DOUBLE PRECISION,
    disk_usage_ratio         DOUBLE PRECISION,
    disk_read_bytes_per_sec  BIGINT,
    disk_write_bytes_per_sec BIGINT,
    net_rx_bytes_per_sec     BIGINT,
    net_tx_bytes_per_sec     BIGINT,
    processes_running        INTEGER,
    processes_zombie         INTEGER
);
SELECT create_hypertable('os_metrics', 'time', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS k8s_metrics (
    time                     TIMESTAMPTZ NOT NULL,
    cluster_name             TEXT NOT NULL,
    node_name                TEXT NOT NULL,
    node_status              TEXT,
    cpu_allocatable          DOUBLE PRECISION,
    cpu_requested            DOUBLE PRECISION,
    cpu_used                 DOUBLE PRECISION,
    cpu_request_ratio        DOUBLE PRECISION,
    cpu_usage_ratio          DOUBLE PRECISION,
    memory_allocatable_bytes BIGINT,
    memory_requested_bytes   BIGINT,
    memory_used_bytes        BIGINT,
    memory_request_ratio     DOUBLE PRECISION,
    memory_usage_ratio       DOUBLE PRECISION,
    pods_running             INTEGER,
    pods_pending             INTEGER,
    pods_failed              INTEGER,
    pods_crash_loop          INTEGER,
    actual_usage_available   BOOLEAN DEFAULT FALSE
);
SELECT create_hypertable('k8s_metrics', 'time', if_not_exists => TRUE);

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
CREATE INDEX IF NOT EXISTS idx_events_severity     ON events(severity) WHERE NOT resolved;

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
    start_offset      => INTERVAL '3 hours',
    end_offset        => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists     => TRUE
);

SELECT add_retention_policy('os_metrics', INTERVAL '90 days', if_not_exists => TRUE);
"""


async def init_schema(pool) -> None:
    """스키마를 초기화한다. 이미 존재하면 건너뛴다."""
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA_SQL)
        try:
            await conn.execute(CONTINUOUS_AGGREGATE_SQL)
        except Exception:
            pass  # 집계 뷰 이미 존재 또는 TimescaleDB 버전 차이
