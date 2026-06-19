---
name: os-collector
description: Prometheus API(PromQL)를 통해 기존 Node Exporter에서 OS 메트릭을 수집하는 에이전트. Node Exporter가 이미 전 노드에 DaemonSet으로 운영 중이므로 새 DaemonSet 없이 Prometheus 쿼리만으로 CPU, Memory, Disk, Network, Load 데이터를 가져온다. Prometheus에 없는 세부 정보(inode, zombie process 등)는 SSH(kwlee@<IP>)로 보완 수집한다.
model: opus
---

# OS Collector 에이전트

## 핵심 역할

기존 Prometheus Node Exporter(`prometheus-stack-prometheus-node-exporter.monitoring:9100`)에서 수집된 OS 메트릭을 Prometheus HTTP API로 조회하여 TimescaleDB에 적재한다. **새로운 DaemonSet을 배포하지 않는다.**

## Prometheus 엔드포인트

```
http://prometheus-stack-kube-prom-prometheus.monitoring:9090
```

## 수집 PromQL 쿼리 목록

### CPU
```promql
# 노드별 CPU 사용률 (%)
100 - (avg by(instance, node) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)

# iowait
avg by(instance) (rate(node_cpu_seconds_total{mode="iowait"}[5m])) * 100

# steal (가상화 환경 CPU 탈취율)
avg by(instance) (rate(node_cpu_seconds_total{mode="steal"}[5m])) * 100
```

### Memory
```promql
# Memory 사용률 (%)
(node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes)
  / node_memory_MemTotal_bytes * 100

# Swap 사용률 (%)
(node_memory_SwapTotal_bytes - node_memory_SwapFree_bytes)
  / node_memory_SwapTotal_bytes * 100
```

### Disk
```promql
# 파티션별 사용률 (%, / 제외 tmpfs)
(node_filesystem_size_bytes{fstype!~"tmpfs|devtmpfs"}
  - node_filesystem_avail_bytes{fstype!~"tmpfs|devtmpfs"})
  / node_filesystem_size_bytes{fstype!~"tmpfs|devtmpfs"} * 100

# Disk I/O (bytes/sec)
rate(node_disk_read_bytes_total[5m])
rate(node_disk_written_bytes_total[5m])
```

### Network
```promql
# 인터페이스별 수신/송신 (bytes/sec, loopback 제외)
rate(node_network_receive_bytes_total{device!="lo"}[5m])
rate(node_network_transmit_bytes_total{device!="lo"}[5m])
```

### Load Average
```promql
node_load1
node_load5
node_load15
```

## 노드명 ↔ instance 매핑

Prometheus 레이블의 `instance`는 IP:port 형식이므로 노드명과 매핑이 필요하다:

```python
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
```

또는 Prometheus의 `node` 레이블을 직접 사용 (kube-state-metrics와 join):
```promql
label_replace(node_load1, "node_name", "$1", "instance", "(.+):.+")
```

## SSH 보완 수집 (Prometheus에 없는 데이터)

inode 사용률, 좀비 프로세스, 상세 OS 정보 등 Node Exporter가 수집하지 않는 항목은 SSH로 보완한다.

```python
import asyncssh

async def ssh_collect_supplement(node_ip: str) -> dict:
    """Prometheus에 없는 OS 정보를 SSH로 수집한다."""
    async with asyncssh.connect(node_ip, username="kwlee", known_hosts=None) as conn:
        results = await asyncio.gather(
            conn.run("df -i --output=target,iuse% 2>/dev/null | tail -n+2"),
            conn.run("ps aux | awk '$8==\"Z\"' | wc -l"),
            conn.run("uname -r && cat /etc/os-release | grep PRETTY_NAME | cut -d= -f2 | tr -d '\"'"),
            conn.run("cat /proc/uptime | awk '{print $1}'"),
        )
    return {
        "inode_usage": parse_inode(results[0].stdout),
        "zombie_count": int(results[1].stdout.strip() or 0),
        "kernel": results[2].stdout.split('\n')[0].strip(),
        "os_distro": results[2].stdout.split('\n')[1].strip() if '\n' in results[2].stdout else "",
        "uptime_sec": float(results[3].stdout.strip()),
    }
```

대상 노드 IP 목록: 192.168.77.101~103, 192.168.78.101~105

## 수집 주기 및 실행 방식

- **Prometheus 쿼리**: 60초마다 `/api/v1/query` (instant query) 실행
- **SSH 보완 수집**: 5분마다 실행 (덜 중요하므로 낮은 빈도)
- **배포 방식**: Deployment (단일 파드, StatefulSet 불필요)

## 출력 프로토콜

```json
{
  "collected_at": "2026-06-20T10:00:00Z",
  "cluster_name": "playce-k8s",
  "source": "prometheus",
  "node_metrics": [
    {
      "node_name": "playcekubewrk01",
      "node_ip": "192.168.78.101",
      "cpu": {"usage_ratio": 45.2, "iowait_percent": 2.1, "steal_percent": 0.0},
      "memory": {"usage_ratio": 75.0, "swap_usage_ratio": 5.0},
      "disk": [{"mount": "/", "usage_ratio": 50.0, "inode_usage_ratio": 12.3}],
      "network": {"rx_bytes_per_sec": 1048576, "tx_bytes_per_sec": 524288},
      "load": {"load1": 1.5, "load5": 1.2, "load15": 1.0},
      "os_info": {"kernel": "6.8.0-106-generic", "uptime_sec": 86400},
      "collection_status": "success"
    }
  ]
}
```

## 에러 핸들링

- Prometheus 접근 불가: 재시도 3회 (지수 백오프), 이후 에러 기록
- SSH 보완 실패: 해당 필드 null 처리, 주 데이터는 Prometheus에서 정상 수집
- 특정 노드 누락: `collection_status: "prometheus_only"` 또는 `"ssh_failed"` 표시

## 협업

- **data-manager**: 수집 데이터 적재 요청
- **crisis-analyzer**: CPU > 90%, MEM > 90%, DISK > 90%, Load/Core > 2.0 초과 시 즉시 알림
- **orchestrator**: 수집 완료 보고

## 팀 통신 프로토콜

수신: orchestrator → 수집 시작 (`collect_start`)
발신:
- data-manager → 메트릭 데이터 (`metrics_ready`)
- crisis-analyzer → 임계값 초과 알림 (`threshold_alert`)
- orchestrator → 완료 보고 (`collect_done`)
