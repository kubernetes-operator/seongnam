"""Loki 기반 Linux 시스템 로그(systemd journal) 조회·분석 서비스.

호스트 저널은 deploy/logging/host-journal-promtail.yaml 이 job="systemd-journal"
스트림으로 Loki 에 적재한다(라벨: node_name, unit, priority). 이 서비스는 그
스트림을 LogQL 로 조회하여 최근 로그 / 요약 통계 / 알려진 이상 시그니처를 제공한다.
"""
import logging
import os
import time

import httpx

logger = logging.getLogger(__name__)

LOKI_URL = os.getenv("LOKI_URL", "http://loki-stack.logging:3100")

# priority(우선순위) 심각도 순서 — 필터 "경고 이상" 판정용
PRIORITY_ORDER = ["emerg", "alert", "crit", "error", "warning", "notice", "info", "debug"]

# 알려진 시스템 로그 이상 시그니처 (프로액티브 탐지)
LOG_SIGNATURES = [
    {"key": "oom",          "label": "메모리 부족(OOM Kill)",        "severity": "critical", "regex": "(?i)(out of memory|oom-kill|killed process|memory cgroup out of memory)"},
    {"key": "kernel_panic", "label": "커널 패닉/Oops",               "severity": "critical", "regex": "(?i)(kernel panic|BUG: unable to handle|general protection fault|Oops:)"},
    {"key": "io_error",     "label": "디스크 I/O 오류",              "severity": "critical", "regex": "(?i)(I/O error|blk_update_request|end_request: I/O error)"},
    {"key": "fs_error",     "label": "파일시스템 오류",              "severity": "critical", "regex": "(?i)(EXT4-fs error|XFS.*Corruption|remounting filesystem read-only)"},
    {"key": "disk_full",    "label": "디스크 공간 부족",             "severity": "warning",  "regex": "(?i)(no space left|enospc|disk full)"},
    {"key": "segfault",     "label": "세그먼테이션 오류",            "severity": "warning",  "regex": "(?i)(segfault|segmentation fault|core dumped)"},
    {"key": "hung_task",    "label": "태스크 행/소프트 락업",        "severity": "warning",  "regex": "(?i)(hung task|soft lockup|rcu.*stall|watchdog: BUG)"},
    {"key": "auth_fail",    "label": "인증 실패(브루트포스 의심)",   "severity": "warning",  "regex": "(?i)(authentication failure|failed password|invalid user|possible break-in)"},
    {"key": "service_fail", "label": "서비스 기동 실패",             "severity": "warning",  "regex": "(?i)(Failed to start|entered failed state|status=1/FAILURE)"},
]


def _ns_range(minutes: int) -> tuple[int, int]:
    end = int(time.time()) * 1_000_000_000
    return end - minutes * 60 * 1_000_000_000, end


def _escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _selector(node_name: str = "", priority: str = "") -> str:
    parts = ['job="systemd-journal"']
    if node_name:
        parts.append(f'node_name="{_escape(node_name)}"')
    if priority:
        parts.append(f'priority="{_escape(priority)}"')
    return "{" + ",".join(parts) + "}"


async def _query_range(logql: str, minutes: int, limit: int = 100) -> list:
    start, end = _ns_range(minutes)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{LOKI_URL}/loki/api/v1/query_range",
                params={"query": logql, "start": start, "end": end, "limit": limit, "direction": "backward"},
            )
            resp.raise_for_status()
            return resp.json().get("data", {}).get("result", [])
    except Exception as e:
        logger.warning("Loki query_range 실패: %s (%s)", e, logql)
        return []


async def _query_instant(logql: str) -> list:
    _, end = _ns_range(1)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{LOKI_URL}/loki/api/v1/query", params={"query": logql, "time": end})
            resp.raise_for_status()
            return resp.json().get("data", {}).get("result", [])
    except Exception as e:
        logger.warning("Loki query(instant) 실패: %s (%s)", e, logql)
        return []


async def recent_logs(node_name: str = "", priority: str = "", search: str = "",
                      minutes: int = 60, limit: int = 100) -> list[dict]:
    """최근 시스템 로그 라인 목록(최신순)."""
    logql = _selector(node_name, priority)
    if search:
        logql += f' |~ "(?i){_escape(search)}"'
    streams = await _query_range(logql, minutes, limit)
    lines = []
    for stream in streams:
        labels = stream.get("stream", {})
        for ts_ns, msg in stream.get("values", []):
            lines.append({
                "ts": int(ts_ns) // 1_000_000_000,
                "node_name": labels.get("node_name", ""),
                "unit": labels.get("unit", ""),
                "priority": labels.get("priority", ""),
                "message": msg[:500],
            })
    lines.sort(key=lambda x: x["ts"], reverse=True)
    return lines[:limit]


async def summary(minutes: int = 60) -> dict:
    """우선순위/노드별 로그 건수 요약."""
    rng = f"[{minutes}m]"

    async def _counts(by_label: str) -> dict:
        res = await _query_instant(f"sum by ({by_label}) (count_over_time({{job=\"systemd-journal\"}}{rng}))")
        out = {}
        for item in res:
            key = item.get("metric", {}).get(by_label, "")
            try:
                out[key] = int(float(item.get("value", [0, "0"])[1]))
            except (ValueError, IndexError):
                pass
        return out

    by_priority = await _counts("priority")
    by_node = await _counts("node_name")
    warn_plus = sum(v for k, v in by_priority.items()
                    if k in ("emerg", "alert", "crit", "error", "warning"))
    return {
        "window_minutes": minutes,
        "total": sum(by_priority.values()),
        "warning_plus": warn_plus,
        "by_priority": by_priority,
        "by_node": by_node,
    }


async def detect_patterns(node_name: str = "", minutes: int = 60) -> list[dict]:
    """알려진 이상 시그니처 탐지 — 매칭된 것만 건수·샘플과 함께 반환."""
    base = _selector(node_name)
    results = []
    for sig in LOG_SIGNATURES:
        logql_expr = f'{base} |~ "{sig["regex"]}"'
        # 노드별로 집계하여 어느 노드에서 발생했는지 표기
        count_res = await _query_instant(f"sum by (node_name) (count_over_time({logql_expr} {'[' + str(minutes) + 'm]'}))")
        nodes = {}
        for item in count_res:
            nn = item.get("metric", {}).get("node_name", "")
            try:
                c = int(float(item.get("value", [0, "0"])[1]))
            except (ValueError, IndexError):
                c = 0
            if c > 0:
                nodes[nn] = nodes.get(nn, 0) + c
        count = sum(nodes.values())
        if count <= 0:
            continue
        samples = await _query_range(logql_expr, minutes, limit=3)
        sample_lines = []
        for stream in samples:
            for _, msg in stream.get("values", []):
                sample_lines.append(msg[:300])
        results.append({
            "key": sig["key"],
            "label": sig["label"],
            "severity": sig["severity"],
            "count": count,
            # 건수 많은 노드 순으로 정렬한 [{node, count}]
            "nodes": [{"node": n, "count": c} for n, c in sorted(nodes.items(), key=lambda x: -x[1])],
            "samples": sample_lines[:3],
        })
    results.sort(key=lambda r: (r["severity"] != "critical", -r["count"]))
    return results
