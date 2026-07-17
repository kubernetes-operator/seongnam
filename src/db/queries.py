"""TimescaleDB 쿼리 함수 모음."""
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional


def _to_timedelta(interval) -> timedelta:
    """'1h', '1d', '7d' 같은 문자열을 timedelta로 변환한다."""
    if isinstance(interval, timedelta):
        return interval
    s = str(interval).strip()
    if s.endswith("h"):
        return timedelta(hours=int(s[:-1]))
    if s.endswith("d"):
        return timedelta(days=int(s[:-1]))
    if s.endswith("m"):
        return timedelta(minutes=int(s[:-1]))
    raise ValueError(f"알 수 없는 interval 형식: {s!r}")

logger = logging.getLogger(__name__)


async def upsert_cluster_node(
    pool,
    cluster_name: str,
    node_name: str,
    node_ip: str = "",
    **kwargs,
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO cluster_nodes
                (cluster_name, node_name, node_ip, os_distro,
                 kernel_version, cpu_cores, memory_total_bytes, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
            ON CONFLICT (cluster_name, node_name)
            DO UPDATE SET
                node_ip            = EXCLUDED.node_ip,
                os_distro          = COALESCE(EXCLUDED.os_distro,          cluster_nodes.os_distro),
                kernel_version     = COALESCE(EXCLUDED.kernel_version,     cluster_nodes.kernel_version),
                cpu_cores          = COALESCE(EXCLUDED.cpu_cores,          cluster_nodes.cpu_cores),
                memory_total_bytes = COALESCE(EXCLUDED.memory_total_bytes, cluster_nodes.memory_total_bytes),
                updated_at         = NOW()
            """,
            cluster_name,
            node_name,
            node_ip or "",
            kwargs.get("os_distro"),
            kwargs.get("kernel_version"),
            kwargs.get("cpu_cores"),
            kwargs.get("memory_total_bytes"),
        )


async def insert_os_metrics(pool, records: list[dict]) -> int:
    """OS 메트릭을 배치 삽입한다."""
    if not records:
        return 0

    columns = [
        "time", "cluster_name", "node_name",
        "cpu_usage_ratio", "cpu_iowait_percent",
        "memory_usage_ratio", "memory_used_bytes", "swap_usage_ratio",
        "load1", "load5", "load15", "load_per_core",
        "disk_usage_ratio", "disk_read_bytes_per_sec", "disk_write_bytes_per_sec",
        "net_rx_bytes_per_sec", "net_tx_bytes_per_sec",
        "processes_running", "processes_zombie",
    ]

    rows = []
    for r in records:
        cpu = r.get("cpu", {})
        mem = r.get("memory", {})
        disk = r.get("disk", {})
        net = r.get("network", {})
        load = r.get("load", {})
        rows.append((
            datetime.now(timezone.utc),
            r.get("cluster_name", ""),
            r.get("node_name", ""),
            cpu.get("usage_ratio"),
            cpu.get("iowait_percent"),
            mem.get("usage_ratio"),
            mem.get("used_bytes"),
            mem.get("swap_usage_ratio"),
            load.get("load1"),
            load.get("load5"),
            load.get("load15"),
            load.get("load_per_core"),
            disk.get("usage_ratio"),
            disk.get("read_bytes_per_sec"),
            disk.get("write_bytes_per_sec"),
            net.get("rx_bytes_per_sec"),
            net.get("tx_bytes_per_sec"),
            load.get("processes_running"),
            load.get("processes_zombie"),
        ))

    async with pool.acquire() as conn:
        await conn.copy_records_to_table("os_metrics", records=rows, columns=columns)
    return len(rows)


async def insert_event(pool, event: dict) -> int:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO events (cluster_name, node_name, event_type, severity, message, details)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
            """,
            event.get("cluster_name", ""),
            event.get("node_name"),
            event.get("event_type", "alert"),
            event.get("severity", "warning"),
            event.get("message", ""),
            json.dumps(event.get("details")) if event.get("details") else None,
        )
    return row["id"]


async def query_metric_timeseries(
    pool,
    cluster_name: str,
    node_name: str,
    metric: str,
    start: str,
    end: str,
    interval: str = "1h",
) -> list[dict]:
    # os_metrics_hourly 컬럼명 매핑
    _HOURLY_COL = {
        "cpu_usage_ratio":    "cpu_avg",
        "memory_usage_ratio": "mem_avg",
        "disk_usage_ratio":   "disk_avg",
        "load1":              "load_avg",
        "load_per_core":      "load_avg",
    }
    if interval in ("1h", "2h", "6h") and metric in _HOURLY_COL:
        table, time_col = "os_metrics_hourly", "bucket"
        metric_col = _HOURLY_COL[metric]
    else:
        table, time_col = "os_metrics", "time"
        metric_col = metric

    # asyncpg는 datetime 객체를 요구한다 — 문자열이면 파싱
    def _parse_dt(v):
        if isinstance(v, datetime):
            return v
        return datetime.fromisoformat(str(v))

    sql = f"""
        SELECT
            time_bucket($1::interval, {time_col}) AS bucket,
            avg({metric_col}) AS avg_value,
            max({metric_col}) AS max_value,
            min({metric_col}) AS min_value
        FROM {table}
        WHERE cluster_name = $2
          AND node_name = $3
          AND {time_col} BETWEEN $4 AND $5
        GROUP BY bucket
        ORDER BY bucket ASC
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            sql, _to_timedelta(interval), cluster_name, node_name,
            _parse_dt(start), _parse_dt(end),
        )
    return [
        {
            "time": row["bucket"].isoformat(),
            "avg": round(float(row["avg_value"] or 0), 2),
            "max": round(float(row["max_value"] or 0), 2),
            "min": round(float(row["min_value"] or 0), 2),
        }
        for row in rows
    ]


async def query_top_nodes(
    pool,
    cluster_name: str,
    metric: str = "cpu_usage_ratio",
    limit: int = 5,
    period_hours: int = 24,
) -> list[dict]:
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
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, cluster_name, str(period_hours), limit)
    return [dict(row) for row in rows]


async def query_latest_metrics(pool, cluster_name: str) -> list[dict]:
    """각 노드의 가장 최근 OS 메트릭을 반환한다."""
    sql = """
        SELECT DISTINCT ON (node_name)
            node_name, time,
            cpu_usage_ratio, memory_usage_ratio, disk_usage_ratio,
            load1, load_per_core, net_rx_bytes_per_sec, net_tx_bytes_per_sec
        FROM os_metrics
        WHERE cluster_name = $1
          AND time > NOW() - INTERVAL '10 minutes'
        ORDER BY node_name, time DESC
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, cluster_name)
    return [dict(row) for row in rows]


async def query_events(
    pool,
    cluster_name: str,
    severity: Optional[str] = None,
    resolved: bool = False,
    limit: int = 50,
) -> list[dict]:
    conditions = ["cluster_name = $1", "resolved = $2"]
    params: list = [cluster_name, resolved]
    if severity:
        params.append(severity)
        conditions.append(f"severity = ${len(params)}")

    sql = f"""
        SELECT id, time, cluster_name, node_name, event_type, severity, message, details, resolved, resolved_at
        FROM events
        WHERE {' AND '.join(conditions)}
        ORDER BY time DESC
        LIMIT {limit}
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)
    return [dict(row) for row in rows]


async def resolve_event(pool, event_id: int) -> bool:
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE events SET resolved = TRUE, resolved_at = NOW() WHERE id = $1 AND NOT resolved",
            event_id,
        )
    return result == "UPDATE 1"


async def query_clusters(pool) -> list[dict]:
    sql = """
        SELECT cluster_name, count(*) AS node_count
        FROM cluster_nodes
        GROUP BY cluster_name
        ORDER BY cluster_name
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql)
    return [dict(row) for row in rows]


async def insert_report_record(
    pool,
    report_type: str,
    cluster_name: str,
    period_start,
    period_end,
    files: dict,
    summary: dict,
) -> int:
    async with pool.acquire() as conn:
        for fmt, path in files.items():
            row = await conn.fetchrow(
                """
                INSERT INTO reports (report_type, cluster_name, period_start, period_end, format, file_path, summary)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING id
                """,
                report_type,
                cluster_name,
                period_start,
                period_end,
                fmt,
                path,
                json.dumps(summary),
            )
    return row["id"]
