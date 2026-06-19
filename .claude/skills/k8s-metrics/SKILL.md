---
name: k8s-metrics
description: |
  kubernetes-client-python을 사용하여 Kubernetes API에서 클러스터, 노드, 파드, 디플로이먼트 상태와 리소스 사용량을 수집하는 Python 코드를 구현한다. 다중 클러스터, metrics-server 연동, 권한 최소화를 지원한다. 'K8s 수집', 'kubectl', 'kubernetes-client', 'Pod 상태', '노드 리소스', 'K8s 메트릭 수집' 관련 구현 시 반드시 이 스킬을 사용할 것.
---

# Kubernetes Metrics 수집 스킬

## 구현 패턴

### 핵심 수집 클래스

```python
from kubernetes import client, config
from kubernetes.client.exceptions import ApiException
import asyncio
from typing import Optional

class K8sMetricsCollector:
    """Kubernetes API에서 클러스터 상태를 수집한다."""

    def __init__(self, context: Optional[str] = None):
        """
        context: kubeconfig context 이름. None이면 현재 활성 context 사용.
        클러스터 내부에서 실행 시 load_incluster_config()를 사용한다.
        """
        try:
            config.load_incluster_config()  # Pod 내부 실행
        except config.ConfigException:
            config.load_kube_config(context=context)  # 로컬 실행

        self.core_v1 = client.CoreV1Api()
        self.apps_v1 = client.AppsV1Api()
        self.custom = client.CustomObjectsApi()

    def collect_all(self) -> dict:
        """클러스터 전체 상태를 수집한다."""
        from datetime import datetime, timezone
        return {
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "version": self._get_version(),
            "nodes": self._collect_nodes(),
            "pods_summary": self._collect_pods_summary(),
            "workloads": self._collect_workloads(),
            "recent_warnings": self._collect_events(),
        }

    def _get_version(self) -> str:
        try:
            version_info = client.VersionApi().get_code()
            return version_info.git_version
        except ApiException:
            return "unknown"

    def _collect_nodes(self) -> list[dict]:
        nodes_data = []
        nodes = self.core_v1.list_node()

        # metrics-server에서 실제 사용량 조회
        node_metrics = self._fetch_node_metrics()

        for node in nodes.items:
            name = node.metadata.name
            allocatable = node.status.allocatable or {}
            conditions = {c.type: (c.status == "True")
                         for c in (node.status.conditions or [])}

            # CPU: millicores → cores 변환
            cpu_alloc = self._parse_cpu(allocatable.get("cpu", "0"))
            mem_alloc = self._parse_memory(allocatable.get("memory", "0"))

            # 파드에서 requests 합계 계산
            cpu_req, mem_req = self._sum_node_requests(name)

            # metrics-server 실제 사용량
            used = node_metrics.get(name, {})

            nodes_data.append({
                "name": name,
                "status": "Ready" if conditions.get("Ready") else "NotReady",
                "allocatable": {
                    "cpu_cores": cpu_alloc,
                    "memory_bytes": mem_alloc,
                },
                "requested": {
                    "cpu_cores": cpu_req,
                    "memory_bytes": mem_req,
                },
                "used": used or None,
                "cpu_request_ratio": round(cpu_req / cpu_alloc * 100, 2) if cpu_alloc else 0,
                "cpu_usage_ratio": round(used.get("cpu_cores", 0) / cpu_alloc * 100, 2) if used and cpu_alloc else None,
                "memory_request_ratio": round(mem_req / mem_alloc * 100, 2) if mem_alloc else 0,
                "memory_usage_ratio": round(used.get("memory_bytes", 0) / mem_alloc * 100, 2) if used and mem_alloc else None,
                "actual_usage_available": bool(used),
                "conditions": conditions,
                "labels": node.metadata.labels or {},
            })

        return nodes_data

    def _fetch_node_metrics(self) -> dict:
        """metrics-server에서 노드 실제 사용량을 조회한다."""
        try:
            metrics = self.custom.list_cluster_custom_object(
                group="metrics.k8s.io",
                version="v1beta1",
                plural="nodes"
            )
            result = {}
            for item in metrics.get("items", []):
                name = item["metadata"]["name"]
                usage = item.get("usage", {})
                result[name] = {
                    "cpu_cores": self._parse_cpu(usage.get("cpu", "0")),
                    "memory_bytes": self._parse_memory(usage.get("memory", "0")),
                }
            return result
        except ApiException as e:
            if e.status == 404:
                # metrics-server 미설치
                return {}
            raise

    def _collect_pods_summary(self) -> dict:
        """전체 파드 상태 요약."""
        pods = self.core_v1.list_pod_for_all_namespaces()
        summary = {"total": 0, "running": 0, "pending": 0, "failed": 0, "crash_loop": 0}

        for pod in pods.items:
            summary["total"] += 1
            phase = pod.status.phase or "Unknown"
            if phase == "Running":
                summary["running"] += 1
            elif phase == "Pending":
                summary["pending"] += 1
            elif phase in ("Failed", "Unknown"):
                summary["failed"] += 1

            # CrashLoopBackOff 감지
            for cs in (pod.status.container_statuses or []):
                waiting = cs.state.waiting if cs.state else None
                if waiting and waiting.reason == "CrashLoopBackOff":
                    summary["crash_loop"] += 1
                    break

        return summary

    def _collect_workloads(self) -> dict:
        deployments = self.apps_v1.list_deployment_for_all_namespaces()
        degraded = sum(
            1 for d in deployments.items
            if (d.status.ready_replicas or 0) < (d.spec.replicas or 0)
        )
        return {
            "deployments_total": len(deployments.items),
            "deployments_degraded": degraded,
        }

    def _collect_events(self, minutes: int = 60) -> list[dict]:
        """최근 Warning 이벤트를 수집한다."""
        from datetime import datetime, timezone, timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)

        events = self.core_v1.list_event_for_all_namespaces(
            field_selector="type=Warning"
        )
        result = []
        for ev in events.items:
            last_time = ev.last_timestamp
            if last_time and last_time.replace(tzinfo=timezone.utc) > cutoff:
                result.append({
                    "type": ev.reason,
                    "namespace": ev.namespace,
                    "object": f"{ev.involved_object.kind}/{ev.involved_object.name}",
                    "message": ev.message,
                    "count": ev.count,
                    "last_seen": last_time.isoformat() if last_time else None,
                })
        return result

    # --- 파싱 유틸리티 ---

    def _parse_cpu(self, cpu_str: str) -> float:
        """'250m' → 0.25, '2' → 2.0 코어 단위로 변환."""
        if cpu_str.endswith("m"):
            return int(cpu_str[:-1]) / 1000
        return float(cpu_str)

    def _parse_memory(self, mem_str: str) -> int:
        """'512Mi' → bytes 변환."""
        units = {"Ki": 1024, "Mi": 1024**2, "Gi": 1024**3,
                 "K": 1000, "M": 1000**2, "G": 1000**3}
        for suffix, mult in units.items():
            if mem_str.endswith(suffix):
                return int(mem_str[:-len(suffix)]) * mult
        return int(mem_str)

    def _sum_node_requests(self, node_name: str) -> tuple[float, int]:
        """특정 노드의 모든 파드 CPU/Memory requests 합계."""
        pods = self.core_v1.list_pod_for_all_namespaces(
            field_selector=f"spec.nodeName={node_name},status.phase=Running"
        )
        cpu_total, mem_total = 0.0, 0
        for pod in pods.items:
            for container in pod.spec.containers:
                req = (container.resources.requests or {}) if container.resources else {}
                cpu_total += self._parse_cpu(req.get("cpu", "0"))
                mem_total += self._parse_memory(req.get("memory", "0"))
        return cpu_total, mem_total
```

## RBAC 설정 (최소 권한)

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: k8s-monitor-reader
rules:
- apiGroups: [""]
  resources: ["nodes", "pods", "events", "namespaces", "services"]
  verbs: ["get", "list", "watch"]
- apiGroups: ["apps"]
  resources: ["deployments", "statefulsets", "daemonsets"]
  verbs: ["get", "list"]
- apiGroups: ["metrics.k8s.io"]
  resources: ["nodes", "pods"]
  verbs: ["get", "list"]
```

## 다중 클러스터 수집

```python
async def collect_all_clusters(cluster_configs: list[dict]) -> list[dict]:
    """여러 클러스터를 병렬로 수집한다."""
    async def collect_one(cfg):
        try:
            collector = K8sMetricsCollector(context=cfg["context"])
            data = collector.collect_all()
            data["cluster_name"] = cfg["name"]
            return data
        except Exception as e:
            return {"cluster_name": cfg["name"], "error": str(e), "status": "failed"}

    tasks = [collect_one(cfg) for cfg in cluster_configs]
    return await asyncio.gather(*tasks)
```

## 의존성

```
kubernetes>=28.1.0
```
