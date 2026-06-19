---
name: crisis-detection
description: |
  OS 및 Kubernetes 메트릭 임계값 초과를 감지하고, 로그를 분석하여 위기 원인을 진단하며, 해결 방안과 공식 문서 링크를 제시하는 Python 코드를 구현한다. '위기 감지', '임계값 초과', '알람', '로그 분석', '해결 방안', '위기 관리', 'Crisis Management', 'OOM', 'CrashLoop' 관련 구현 시 반드시 이 스킬을 사용할 것.
---

# Crisis Detection 스킬

## 위기 카탈로그

```python
# crisis_catalog.py
CRISIS_CATALOG = {
    "HIGH_CPU": {
        "description": "CPU 사용률이 임계값을 초과했습니다.",
        "diagnosis_steps": [
            "top 또는 ps aux --sort=-%cpu 실행하여 고사용 프로세스 확인",
            "dmesg | grep -i throttl 실행하여 CPU 쓰로틀링 확인",
        ],
        "immediate_actions": [
            "과도한 CPU를 사용하는 프로세스를 확인하고 종료 또는 재시작",
            "nice -n 10 <pid> 로 우선순위를 낮춰 다른 프로세스 영향 최소화",
            "K8s: kubectl top pods --all-namespaces | sort -k3 -rn | head -10",
        ],
        "references": [
            {
                "title": "Linux CPU 성능 최적화",
                "url": "https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html"
            },
            {
                "title": "Kubernetes CPU 리소스 관리",
                "url": "https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/"
            }
        ],
    },
    "MEMORY_EXHAUSTION": {
        "description": "메모리 사용률이 위험 수준에 도달했습니다. OOM Killer 활성화 위험.",
        "log_patterns": [
            r"Out of memory: Kill process",
            r"oom-kill",
            r"Memory cgroup out of memory",
        ],
        "diagnosis_steps": [
            "dmesg | grep -i 'oom' | tail -20",
            "cat /proc/meminfo | grep -E 'MemTotal|MemFree|MemAvailable'",
            "ps aux --sort=-%mem | head -15",
        ],
        "immediate_actions": [
            "메모리 누수 프로세스를 확인하고 재시작: systemctl restart <service>",
            "페이지 캐시 해제 (운영 영향 최소): sync && echo 1 > /proc/sys/vm/drop_caches",
            "K8s: kubectl describe pod <pod> | grep -A5 OOM",
            "K8s memory limit 증가: kubectl set resources deployment <name> --limits memory=2Gi",
        ],
        "references": [
            {
                "title": "Linux Kernel OOM Killer",
                "url": "https://www.kernel.org/doc/html/latest/admin-guide/mm/concepts.html"
            },
            {
                "title": "Kubernetes OOM 문제 해결",
                "url": "https://kubernetes.io/docs/tasks/configure-pod-container/assign-memory-resource/"
            }
        ],
    },
    "DISK_FULL": {
        "description": "디스크 사용률이 임계값을 초과했습니다. 쓰기 오류 발생 위험.",
        "diagnosis_steps": [
            "df -h 전체 파티션 사용률 확인",
            "du -sh /var/log/* 2>/dev/null | sort -hr | head -20 로그 크기 확인",
            "du -sh /var/lib/docker/overlay2/* 2>/dev/null | sort -hr | head -10 Docker 레이어 확인",
        ],
        "immediate_actions": [
            "오래된 로그 삭제: journalctl --vacuum-size=500M",
            "Docker 정리: docker system prune -f (사용하지 않는 이미지/컨테이너 삭제)",
            "K8s: kubectl delete pod --field-selector=status.phase=Failed --all-namespaces",
            "임시 파일 삭제: find /tmp -type f -mtime +7 -delete",
        ],
        "references": [
            {
                "title": "Linux 디스크 관리",
                "url": "https://man7.org/linux/man-pages/man8/fdisk.8.html"
            },
            {
                "title": "Kubernetes 노드 디스크 압력",
                "url": "https://kubernetes.io/docs/concepts/scheduling-eviction/node-pressure-eviction/"
            }
        ],
    },
    "HIGH_LOAD": {
        "description": "시스템 Load Average가 CPU 코어 수의 2배를 초과했습니다.",
        "diagnosis_steps": [
            "iostat -x 1 5 (I/O 병목 확인)",
            "vmstat 1 5 (CPU wait, blocked 프로세스 확인)",
            "iotop -o (I/O 집중 프로세스 확인)",
        ],
        "immediate_actions": [
            "I/O 집중 프로세스 확인 및 우선순위 조정",
            "디스크 I/O 스케줄러 확인: cat /sys/block/sda/queue/scheduler",
        ],
        "references": [
            {"title": "Linux Load Average 이해", "url": "https://www.brendangregg.com/blog/2017-08-08/linux-load-averages.html"},
        ],
    },
    "CRASHLOOP_BACKOFF": {
        "description": "Kubernetes 파드가 반복 재시작(CrashLoopBackOff) 상태입니다.",
        "diagnosis_steps": [
            "kubectl logs <pod> --previous (이전 컨테이너 로그)",
            "kubectl describe pod <pod> (Events 섹션 확인)",
            "kubectl get events --field-selector involvedObject.name=<pod>",
        ],
        "immediate_actions": [
            "이전 로그에서 오류 원인 분석",
            "환경변수/ConfigMap/Secret 설정 확인",
            "이미지 태그 및 레지스트리 접근 확인",
            "리소스 제한 초과 여부: kubectl top pod <pod>",
        ],
        "references": [
            {"title": "Kubernetes Pod 라이프사이클", "url": "https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/"},
            {"title": "CrashLoopBackOff 해결 가이드", "url": "https://kubernetes.io/docs/tasks/debug/debug-application/debug-running-pod/"},
        ],
    },
    "NODE_NOT_READY": {
        "description": "Kubernetes 노드가 NotReady 상태입니다.",
        "diagnosis_steps": [
            "kubectl describe node <node> (Conditions, Events 확인)",
            "ssh <node> 'systemctl status kubelet'",
            "ssh <node> 'journalctl -u kubelet --since \"10 min ago\"'",
        ],
        "immediate_actions": [
            "kubelet 재시작: systemctl restart kubelet",
            "노드 네트워크 연결 확인: ping <api-server-ip>",
            "디스크 압력 확인: df -h (ImageFS, NodeFS)",
        ],
        "references": [
            {"title": "Kubernetes 노드 문제 해결", "url": "https://kubernetes.io/docs/tasks/debug/debug-cluster/"},
        ],
    },
    "OOM_KILLED": {
        "description": "컨테이너가 메모리 한계 초과로 종료(OOMKilled)되었습니다.",
        "diagnosis_steps": [
            "kubectl describe pod <pod> | grep -A5 'Last State'",
            "kubectl get events | grep OOM",
            "dmesg | grep oom | tail -10",
        ],
        "immediate_actions": [
            "memory limit을 현재 사용량의 1.5배 이상으로 증가",
            "애플리케이션 메모리 프로파일링 수행",
            "JVM 사용 시: JAVA_OPTS '-Xmx' 값 조정",
        ],
        "references": [
            {"title": "Kubernetes 메모리 리소스 관리", "url": "https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/"},
        ],
    },
}
```

## 위기 감지 엔진

```python
# crisis_engine.py
import re
from datetime import datetime, timezone
from crisis_catalog import CRISIS_CATALOG

class CrisisEngine:
    """메트릭과 로그를 분석하여 위기를 감지하고 진단한다."""

    THRESHOLDS = {
        "os": {
            "cpu_usage_ratio":    {"warning": 80, "critical": 90},
            "memory_usage_ratio": {"warning": 80, "critical": 90},
            "swap_usage_ratio":   {"warning": 50, "critical": 80},
            "disk_usage_ratio":   {"warning": 75, "critical": 90},
            "load_per_core":      {"warning": 1.5, "critical": 2.0},
        },
        "k8s": {
            "cpu_usage_ratio":    {"warning": 75, "critical": 90},
            "memory_usage_ratio": {"warning": 80, "critical": 90},
        },
    }

    # 중복 경보 억제: (node, crisis_type) → 마지막 경보 시각
    _last_alert: dict = {}
    DEDUP_SECONDS = 300  # 5분 내 동일 경보 중복 제거

    def check_os_metrics(self, cluster: str, node: str, metrics: dict) -> list[dict]:
        """OS 메트릭에서 임계값 초과를 감지한다."""
        alerts = []
        thresholds = self.THRESHOLDS["os"]

        # CPU
        cpu = metrics.get("cpu", {}).get("usage_ratio", 0)
        if cpu >= thresholds["cpu_usage_ratio"]["critical"]:
            alerts.append(self._build_alert(cluster, node, "HIGH_CPU", "critical", "cpu_usage_ratio", cpu))

        # Memory
        mem = metrics.get("memory", {}).get("usage_ratio", 0)
        if mem >= thresholds["memory_usage_ratio"]["critical"]:
            alerts.append(self._build_alert(cluster, node, "MEMORY_EXHAUSTION", "critical", "memory_usage_ratio", mem))

        # Disk — 모든 파티션 체크
        for disk in metrics.get("disk", []):
            dr = disk.get("usage_ratio", 0)
            if dr >= thresholds["disk_usage_ratio"]["critical"]:
                alerts.append(self._build_alert(
                    cluster, node, "DISK_FULL", "critical", "disk_usage_ratio", dr,
                    extra={"mount": disk["mount"]}
                ))

        # Load
        load_per_core = metrics.get("load", {}).get("load_per_core", 0)
        if load_per_core >= thresholds["load_per_core"]["critical"]:
            alerts.append(self._build_alert(cluster, node, "HIGH_LOAD", "critical", "load_per_core", load_per_core))

        return [a for a in alerts if a is not None]

    def analyze_logs(self, crisis_type: str, log_lines: list[str]) -> list[str]:
        """로그에서 위기 패턴을 매칭하여 증거를 추출한다."""
        catalog = CRISIS_CATALOG.get(crisis_type, {})
        patterns = catalog.get("log_patterns", [])
        evidence = []
        for line in log_lines:
            for pattern in patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    evidence.append(line.strip())
                    break
        return evidence[:10]  # 최대 10줄

    def build_crisis_report(
        self, crisis_type: str, cluster: str, node: str,
        metric_name: str, metric_value: float,
        log_evidence: list[str] = None
    ) -> dict:
        """위기 분석 리포트를 생성한다."""
        catalog = CRISIS_CATALOG.get(crisis_type, {})
        return {
            "crisis_id": f"crisis-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}",
            "detected_at": datetime.now(timezone.utc).isoformat(),
            "severity": "critical",
            "cluster_name": cluster,
            "node_name": node,
            "crisis_type": crisis_type,
            "description": catalog.get("description", ""),
            "trigger_metric": {"name": metric_name, "value": metric_value},
            "diagnosis": {
                "steps": catalog.get("diagnosis_steps", []),
                "log_evidence": log_evidence or [],
            },
            "remediation": {
                "immediate_actions": catalog.get("immediate_actions", []),
                "references": catalog.get("references", []),
            },
            "status": "open",
            "auto_resolved": False,
        }

    def _build_alert(
        self, cluster, node, crisis_type, severity, metric, value, extra=None
    ) -> dict | None:
        """중복 억제 후 알림을 생성한다."""
        key = f"{cluster}:{node}:{crisis_type}"
        now = datetime.now(timezone.utc).timestamp()
        last = self._last_alert.get(key, 0)
        if now - last < self.DEDUP_SECONDS:
            return None  # 중복 제거
        self._last_alert[key] = now
        alert = {
            "cluster": cluster, "node": node,
            "crisis_type": crisis_type, "severity": severity,
            "metric": metric, "value": value,
        }
        if extra:
            alert.update(extra)
        return alert
```

## 의존성

```
# 추가 의존성 없음 (표준 라이브러리 + 기존 패키지)
```
