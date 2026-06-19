"""위기 감지 엔진 — 임계값 초과 감지, Loki 로그 조회, 위기 리포트 생성."""
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional

import httpx

from analysis.crisis_catalog import CRISIS_CATALOG

logger = logging.getLogger(__name__)

LOKI_URL = "http://loki-stack.logging:3100"

LOKI_QUERIES = {
    "MEMORY_EXHAUSTION": {
        "system": '{job="systemd-journal"} |~ "(?i)(oom|out of memory|memory cgroup)"',
        "k8s":    '{namespace=~".+"} |~ "(?i)(OOMKilled|memory limit)"',
    },
    "CRASHLOOP_BACKOFF": {
        "k8s": '{namespace=~".+"} |~ "(?i)(CrashLoopBackOff|Back-off restarting|failed to start)"',
    },
    "HIGH_CPU": {
        "system": '{job="systemd-journal"} |~ "(?i)(cpu throttl|soft lockup|hung task)"',
    },
    "DISK_FULL": {
        "system": '{job="systemd-journal"} |~ "(?i)(no space left|disk full|write failed|enospc)"',
    },
    "NODE_NOT_READY": {
        "k8s": '{namespace="kube-system"} |~ "(?i)(node not ready|kubelet|connection refused)"',
    },
    "OOM_KILLED": {
        "k8s":    '{namespace=~".+"} |~ "OOMKilled"',
        "system": '{job="systemd-journal"} |~ "oom-kill"',
    },
    "HIGH_LOAD": {
        "system": '{job="systemd-journal"} |~ "(?i)(hung task|soft lockup|io wait)"',
    },
}

# {(node_name, crisis_type): last_alerted_epoch} — 5분 중복 억제
_dedup_cache: dict[tuple, float] = {}
_DEDUP_SECONDS = 300


class CrisisEngine:
    async def query_loki_logs(
        self, crisis_type: str, node_name: str, since_minutes: int = 30
    ) -> list[str]:
        end_ns = int(time.time()) * 1_000_000_000
        start_ns = end_ns - since_minutes * 60 * 1_000_000_000
        evidence = []

        for scope, logql in LOKI_QUERIES.get(crisis_type, {}).items():
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.get(
                        f"{LOKI_URL}/loki/api/v1/query_range",
                        params={"query": logql, "start": start_ns, "end": end_ns, "limit": 20},
                    )
                    if resp.status_code == 200:
                        for stream in resp.json().get("data", {}).get("result", []):
                            for _, line in stream.get("values", []):
                                evidence.append(line[:300])
            except Exception as e:
                logger.warning("Loki 쿼리 실패 (%s/%s): %s", crisis_type, scope, e)

        return evidence[:15]

    def _is_duplicate(self, node_name: str, crisis_type: str) -> bool:
        key = (node_name, crisis_type)
        last = _dedup_cache.get(key, 0)
        if time.time() - last < _DEDUP_SECONDS:
            return True
        _dedup_cache[key] = time.time()
        return False

    async def build_crisis_report(
        self,
        cluster_name: str,
        node_name: str,
        node_ip: str,
        crisis_type: str,
        trigger_metric: dict,
        severity: str = "critical",
    ) -> Optional[dict]:
        if self._is_duplicate(node_name, crisis_type):
            return None

        catalog = CRISIS_CATALOG.get(crisis_type, {})
        loki_evidence = await self.query_loki_logs(crisis_type, node_name)

        return {
            "crisis_id": f"crisis-{int(time.time())}-{node_name[:8]}",
            "detected_at": datetime.now(timezone.utc).isoformat(),
            "severity": severity,
            "cluster_name": cluster_name,
            "node_name": node_name,
            "node_ip": node_ip,
            "crisis_type": crisis_type,
            "description": catalog.get("description", ""),
            "trigger_metric": trigger_metric,
            "loki_evidence": loki_evidence,
            "diagnosis": {
                "steps": catalog.get("diagnosis_steps", []),
            },
            "remediation": {
                "immediate_actions": catalog.get("immediate_actions", []),
                "references": catalog.get("references", []),
            },
            "status": "open",
        }

    async def check_os_metrics(
        self,
        cluster_name: str,
        node_metrics_list: list[dict],
        node_ip_map: dict[str, str],
    ) -> list[dict]:
        """OS 메트릭을 검사하여 위기 리포트 목록을 반환한다."""
        from os_service import THRESHOLDS  # type: ignore

        reports = []
        for nm in node_metrics_list:
            node_name = nm.get("node_name", "")
            node_ip = node_ip_map.get(node_name, "")

            flat = {
                "cpu_usage_ratio":    nm.get("cpu", {}).get("usage_ratio"),
                "memory_usage_ratio": nm.get("memory", {}).get("usage_ratio"),
                "disk_usage_ratio":   nm.get("disk", {}).get("usage_ratio"),
                "load_per_core":      nm.get("load", {}).get("load_per_core"),
            }
            for metric, limits in THRESHOLDS.items():
                value = flat.get(metric)
                if value is None or value < limits["critical"]:
                    continue
                report = await self.build_crisis_report(
                    cluster_name, node_name, node_ip,
                    crisis_type=limits["type"],
                    trigger_metric={"name": metric, "value": value},
                )
                if report:
                    reports.append(report)

        return reports
