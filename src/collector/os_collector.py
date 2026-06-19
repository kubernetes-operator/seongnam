"""Prometheus PromQL을 통해 Node Exporter 메트릭을 수집한다."""
import asyncio
import logging
import math
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

PROMETHEUS_URL = "http://prometheus-stack-kube-prom-prometheus.monitoring:9090"

NODE_MAP = {
    "192.168.77.101:9100": "playcekubectr01",
    "192.168.77.102:9100": "playcekubectr02",
    "192.168.77.103:9100": "playcekubectr03",
    "192.168.78.101:9100": "playcekubewrk01",
    "192.168.78.102:9100": "playcekubewrk02",
    "192.168.78.105:9100": "playcekubewrk03",
    "192.168.78.103:9100": "infra01",
    "192.168.78.104:9100": "infra02",
}

NODE_IP_MAP = {
    "playcekubectr01": "192.168.77.101",
    "playcekubectr02": "192.168.77.102",
    "playcekubectr03": "192.168.77.103",
    "playcekubewrk01": "192.168.78.101",
    "playcekubewrk02": "192.168.78.102",
    "playcekubewrk03": "192.168.78.105",
    "infra01": "192.168.78.103",
    "infra02": "192.168.78.104",
}

PROMQL = {
    "cpu_usage":         '100 - (avg by(instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)',
    "cpu_iowait":        'avg by(instance) (rate(node_cpu_seconds_total{mode="iowait"}[5m])) * 100',
    "memory_usage":      "(node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes) / node_memory_MemTotal_bytes * 100",
    "memory_used_bytes": "node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes",
    "swap_usage":        "(node_memory_SwapTotal_bytes - node_memory_SwapFree_bytes) / node_memory_SwapTotal_bytes * 100",
    "disk_usage":        '(node_filesystem_size_bytes{fstype!~"tmpfs|devtmpfs",mountpoint="/"} - node_filesystem_avail_bytes{fstype!~"tmpfs|devtmpfs",mountpoint="/"}) / node_filesystem_size_bytes{fstype!~"tmpfs|devtmpfs",mountpoint="/"} * 100',
    "disk_read":         "sum by(instance) (rate(node_disk_read_bytes_total[5m]))",
    "disk_write":        "sum by(instance) (rate(node_disk_written_bytes_total[5m]))",
    "net_rx":            'sum by(instance) (rate(node_network_receive_bytes_total{device!="lo"}[5m]))',
    "net_tx":            'sum by(instance) (rate(node_network_transmit_bytes_total{device!="lo"}[5m]))',
    "load1":             "node_load1",
    "load5":             "node_load5",
    "load15":            "node_load15",
}


class PrometheusCollector:
    def __init__(self, prometheus_url: str = PROMETHEUS_URL):
        self.url = prometheus_url

    async def query(self, promql: str) -> dict[str, float]:
        """PromQL instant query. {instance: value} 딕셔너리 반환."""
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{self.url}/api/v1/query",
                params={"query": promql},
            )
            resp.raise_for_status()
            data = resp.json()

        result = {}
        for item in data.get("data", {}).get("result", []):
            instance = item["metric"].get("instance", "")
            if instance:
                try:
                    result[instance] = float(item["value"][1])
                except (ValueError, TypeError):
                    result[instance] = 0.0
        return result

    async def collect_all(self, cluster_name: str = "playce-k8s") -> dict:
        """모든 노드 메트릭을 병렬로 수집한다."""
        collected_at = datetime.now(timezone.utc).isoformat()

        results = await asyncio.gather(
            *[self.query(q) for q in PROMQL.values()],
            return_exceptions=True,
        )
        metric_data = dict(zip(PROMQL.keys(), results))

        node_metrics = []
        for instance, node_name in NODE_MAP.items():
            try:
                load1 = _safe(metric_data["load1"], instance)
                node_metrics.append({
                    "collected_at": collected_at,
                    "cluster_name": cluster_name,
                    "node_name": node_name,
                    "node_ip": NODE_IP_MAP.get(node_name, ""),
                    "cpu": {
                        "usage_ratio":    round(_safe(metric_data["cpu_usage"], instance), 2),
                        "iowait_percent": round(_safe(metric_data["cpu_iowait"], instance), 2),
                    },
                    "memory": {
                        "usage_ratio":      round(_safe(metric_data["memory_usage"], instance), 2),
                        "used_bytes":       int(_safe(metric_data["memory_used_bytes"], instance)),
                        "swap_usage_ratio": round(_nan_zero(_safe(metric_data["swap_usage"], instance)), 2),
                    },
                    "disk": {
                        "usage_ratio":         round(_safe(metric_data["disk_usage"], instance), 2),
                        "read_bytes_per_sec":  int(_safe(metric_data["disk_read"], instance)),
                        "write_bytes_per_sec": int(_safe(metric_data["disk_write"], instance)),
                    },
                    "network": {
                        "rx_bytes_per_sec": int(_safe(metric_data["net_rx"], instance)),
                        "tx_bytes_per_sec": int(_safe(metric_data["net_tx"], instance)),
                    },
                    "load": {
                        "load1":       round(load1, 2),
                        "load5":       round(_safe(metric_data["load5"], instance), 2),
                        "load15":      round(_safe(metric_data["load15"], instance), 2),
                        "load_per_core": round(load1, 2),  # SSH 보완 후 업데이트됨
                    },
                    "collection_status": "success",
                })
            except Exception as e:
                node_metrics.append({
                    "node_name": node_name,
                    "collection_status": "failed",
                    "error": str(e),
                })

        return {
            "collected_at": collected_at,
            "cluster_name": cluster_name,
            "source": "prometheus",
            "node_metrics": node_metrics,
        }


def _safe(data, key: str, default: float = 0.0) -> float:
    if isinstance(data, Exception):
        return default
    v = data.get(key, default)
    return default if v is None else float(v)


def _nan_zero(v: float) -> float:
    return 0.0 if (v is None or math.isnan(v) or math.isinf(v)) else v
