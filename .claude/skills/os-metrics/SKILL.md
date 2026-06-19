---
name: os-metrics
description: |
  Linux OS 메트릭 수집 Python 코드를 구현한다. psutil, subprocess, /proc 파싱을 활용하여 CPU, Memory, Disk, Network, Load Average, Process 정보를 수집하고 구조화된 JSON으로 반환한다. DaemonSet, Node Exporter, SSH 방식 모두 지원. 'OS 수집', 'CPU 메트릭', '메모리 수집', 'psutil', 'Node Exporter', 'Linux 상태 수집' 관련 구현 시 반드시 이 스킬을 사용할 것.
---

# OS Metrics 수집 스킬

## 구현 방식 선택 가이드

| 방식 | 사용 시점 | 장단점 |
|------|----------|-------|
| **DaemonSet + psutil** | K8s 환경 기본값 | 모든 노드 자동 커버, 네트워크 격리 우려 없음 |
| **Node Exporter 연동** | Prometheus 이미 운영 중 | 기존 스택 활용, 재수집 방지 |
| **SSH + paramiko** | K8s 외부 노드 | 에이전트 불필요, 방화벽 제약 있음 |

## Python 구현 패턴

### 핵심 수집 클래스

```python
import psutil
import platform
import time
from datetime import datetime, timezone
from typing import Optional

class OSMetricsCollector:
    """단일 노드의 OS 메트릭을 수집한다."""

    def collect(self, metrics: list[str] = None) -> dict:
        """
        지정된 메트릭을 수집하여 반환한다.
        metrics 미지정 시 전체 수집.
        """
        all_metrics = metrics or ["cpu", "memory", "disk", "network", "load", "os_info"]
        result = {
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "collection_status": "success"
        }

        collectors = {
            "cpu": self._collect_cpu,
            "memory": self._collect_memory,
            "disk": self._collect_disk,
            "network": self._collect_network,
            "load": self._collect_load,
            "os_info": self._collect_os_info,
        }

        failed = []
        for metric in all_metrics:
            try:
                result[metric] = collectors[metric]()
            except Exception as e:
                failed.append({"metric": metric, "error": str(e)})

        if failed:
            result["collection_status"] = "partial"
            result["failed_metrics"] = failed

        return result

    def _collect_cpu(self) -> dict:
        # CPU 사용률: 1초 간격으로 측정 (더 정확함)
        per_cpu = psutil.cpu_percent(interval=1, percpu=True)
        overall = sum(per_cpu) / len(per_cpu)
        cpu_times = psutil.cpu_times_percent(interval=0)
        return {
            "cores": psutil.cpu_count(logical=True),
            "physical_cores": psutil.cpu_count(logical=False),
            "usage_percent": round(overall, 2),
            "usage_ratio": round(overall, 2),  # 최대 대비 비율 (% = ratio here)
            "per_core": [round(p, 2) for p in per_cpu],
            "iowait_percent": round(getattr(cpu_times, 'iowait', 0.0), 2),
            "steal_percent": round(getattr(cpu_times, 'steal', 0.0), 2),
            "ctx_switches": psutil.cpu_stats().ctx_switches,
        }

    def _collect_memory(self) -> dict:
        vm = psutil.virtual_memory()
        swap = psutil.swap_memory()
        return {
            "total_bytes": vm.total,
            "used_bytes": vm.used,
            "available_bytes": vm.available,
            "buffers_bytes": getattr(vm, 'buffers', 0),
            "cached_bytes": getattr(vm, 'cached', 0),
            "usage_ratio": round(vm.percent, 2),
            "swap_total_bytes": swap.total,
            "swap_used_bytes": swap.used,
            "swap_usage_ratio": round(swap.percent, 2),
        }

    def _collect_disk(self) -> list[dict]:
        results = []
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
                io = psutil.disk_io_counters(perdisk=True).get(
                    part.device.split('/')[-1], None
                )
                results.append({
                    "device": part.device,
                    "mount": part.mountpoint,
                    "fstype": part.fstype,
                    "total_bytes": usage.total,
                    "used_bytes": usage.used,
                    "free_bytes": usage.free,
                    "usage_ratio": round(usage.percent, 2),
                    "inode_usage_ratio": self._get_inode_usage(part.mountpoint),
                    "read_bytes_per_sec": getattr(io, 'read_bytes', 0) if io else 0,
                    "write_bytes_per_sec": getattr(io, 'write_bytes', 0) if io else 0,
                })
            except (PermissionError, OSError):
                continue
        return results

    def _collect_network(self) -> dict:
        io = psutil.net_io_counters(pernic=True)
        interfaces = []
        for name, stats in io.items():
            if name == 'lo':
                continue
            interfaces.append({
                "name": name,
                "rx_bytes": stats.bytes_recv,
                "tx_bytes": stats.bytes_sent,
                "rx_packets": stats.packets_recv,
                "tx_packets": stats.packets_sent,
                "rx_errors": stats.errin,
                "tx_errors": stats.errout,
                "rx_drops": stats.dropin,
                "tx_drops": stats.dropout,
            })
        return {"interfaces": interfaces}

    def _collect_load(self) -> dict:
        load = psutil.getloadavg()
        proc_stats = {s.status: 0 for s in psutil.STATUS_RUNNING, psutil.STATUS_ZOMBIE}
        for proc in psutil.process_iter(['status']):
            try:
                s = proc.info['status']
                proc_stats[s] = proc_stats.get(s, 0) + 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return {
            "load1": round(load[0], 2),
            "load5": round(load[1], 2),
            "load15": round(load[2], 2),
            "load_per_core": round(load[0] / (psutil.cpu_count() or 1), 2),
            "processes_total": len(psutil.pids()),
            "processes_running": proc_stats.get(psutil.STATUS_RUNNING, 0),
            "processes_zombie": proc_stats.get(psutil.STATUS_ZOMBIE, 0),
        }

    def _collect_os_info(self) -> dict:
        boot_time = psutil.boot_time()
        return {
            "distro": platform.platform(),
            "kernel": platform.release(),
            "hostname": platform.node(),
            "uptime_sec": int(time.time() - boot_time),
            "python_version": platform.python_version(),
        }

    def _get_inode_usage(self, mountpoint: str) -> float:
        import os
        try:
            st = os.statvfs(mountpoint)
            if st.f_files == 0:
                return 0.0
            return round((1 - st.f_ffree / st.f_files) * 100, 2)
        except OSError:
            return 0.0
```

### DaemonSet 배포 패턴

```python
# collector_service.py — DaemonSet으로 각 노드에서 실행
import asyncio
import asyncpg
from os_metrics import OSMetricsCollector

async def run_collector(db_url: str, interval_sec: int = 60):
    collector = OSMetricsCollector()
    pool = await asyncpg.create_pool(db_url, min_size=2, max_size=5)

    while True:
        metrics = collector.collect()
        node_name = os.environ.get("NODE_NAME", platform.node())
        cluster_name = os.environ.get("CLUSTER_NAME", "default")

        await insert_metrics(pool, cluster_name, node_name, metrics)
        await asyncio.sleep(interval_sec)
```

### Node Exporter 연동 패턴

```python
import httpx

async def fetch_from_node_exporter(node_ip: str, port: int = 9100) -> dict:
    """Prometheus Node Exporter에서 메트릭을 파싱한다."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"http://{node_ip}:{port}/metrics")
    return parse_prometheus_text(resp.text)
```

## 임계값 체크

수집 후 즉시 임계값을 체크하여 crisis-analyzer에 알린다:

```python
THRESHOLDS = {
    "cpu_usage_ratio": {"warning": 80, "critical": 90},
    "memory_usage_ratio": {"warning": 80, "critical": 90},
    "disk_usage_ratio": {"warning": 75, "critical": 90},
    "load_per_core": {"warning": 1.5, "critical": 2.0},
}

def check_thresholds(metrics: dict) -> list[dict]:
    alerts = []
    for metric, limits in THRESHOLDS.items():
        value = metrics.get(metric)
        if value is None:
            continue
        if value >= limits["critical"]:
            alerts.append({"metric": metric, "value": value, "level": "critical"})
        elif value >= limits["warning"]:
            alerts.append({"metric": metric, "value": value, "level": "warning"})
    return alerts
```

## 의존성

```
psutil>=5.9.0
asyncpg>=0.29.0
httpx>=0.25.0
```

## 참고

복수 노드 병렬 수집 패턴은 `references/multi-node-collection.md` 참조.
