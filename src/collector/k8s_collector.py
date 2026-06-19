"""kubernetes-client-python을 사용하여 K8s 상태를 수집한다."""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from kubernetes import client, config
from kubernetes.client.exceptions import ApiException

logger = logging.getLogger(__name__)


class K8sMetricsCollector:
    """Kubernetes API에서 클러스터 상태와 리소스 사용량을 수집한다."""

    def __init__(self, context: Optional[str] = None):
        """
        context: kubeconfig context 이름. None이면 현재 활성 context 사용.
        클러스터 내부에서 실행 시 load_incluster_config()를 사용한다.
        """
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config(context=context)

        self.core_v1 = client.CoreV1Api()
        self.apps_v1 = client.AppsV1Api()
        self.batch_v1 = client.BatchV1Api()
        self.custom = client.CustomObjectsApi()
        self.version_api = client.VersionApi()

    def collect_all(self, cluster_name: str = "playce-k8s") -> dict:
        """클러스터 전체 상태를 수집하여 반환한다."""
        return {
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "cluster_name": cluster_name,
            "k8s_version": self._get_version(),
            "nodes": self._collect_nodes(),
            "pods_summary": self._collect_pods_summary(),
            "workloads": self._collect_workloads(),
            "recent_warnings": self._collect_events(),
        }

    # ------------------------------------------------------------------
    # 버전
    # ------------------------------------------------------------------

    def _get_version(self) -> str:
        """K8s API server 버전을 반환한다."""
        try:
            version_info = self.version_api.get_code()
            return version_info.git_version
        except ApiException as e:
            logger.warning("K8s version fetch failed: %s", e)
            return "unknown"

    # ------------------------------------------------------------------
    # 노드 수집
    # ------------------------------------------------------------------

    def _collect_nodes(self) -> list[dict]:
        """노드별 상태와 리소스 정보를 수집한다."""
        nodes_data = []
        nodes = self.core_v1.list_node()

        # metrics-server에서 실제 사용량 조회 (없으면 빈 dict)
        node_metrics = self._fetch_node_metrics()

        for node in nodes.items:
            name = node.metadata.name
            allocatable = node.status.allocatable or {}
            capacity = node.status.capacity or {}

            # 조건 맵 생성
            conditions = {
                c.type: (c.status == "True")
                for c in (node.status.conditions or [])
            }

            # 노드 IP 조회
            node_ip = ""
            for addr in (node.status.addresses or []):
                if addr.type == "InternalIP":
                    node_ip = addr.address
                    break

            # 노드 OS/커널/역할 정보
            node_info = node.status.node_info or {}
            os_distro = getattr(node_info, "os_image", "") or ""
            kernel_version = getattr(node_info, "kernel_version", "") or ""
            labels = node.metadata.labels or {}
            role_parts = [k.split("/")[-1] for k in labels if k.startswith("node-role.kubernetes.io/")]
            role = ",".join(role_parts) if role_parts else "worker"

            # CPU/Memory 총 용량 (capacity)
            cpu_cap = self._parse_cpu(capacity.get("cpu", "0"))
            mem_cap = self._parse_memory(capacity.get("memory", "0"))

            # CPU: millicores → cores 변환
            cpu_alloc = self._parse_cpu(allocatable.get("cpu", "0"))
            mem_alloc = self._parse_memory(allocatable.get("memory", "0"))

            # 파드에서 requests 합계 계산
            cpu_req, mem_req = self._sum_node_requests(name)

            # metrics-server 실제 사용량
            used = node_metrics.get(name, {})
            cpu_used = used.get("cpu_cores", 0.0) if used else 0.0
            mem_used = used.get("memory_bytes", 0) if used else 0
            actual_usage_available = bool(used)

            # 노드별 파드 현황
            pods_on_node = self._collect_node_pods(name)

            nodes_data.append({
                "name": name,
                "node_ip": node_ip,
                "role": role,
                "os_distro": os_distro,
                "kernel_version": kernel_version,
                "cpu_cores": int(cpu_cap),
                "memory_total_bytes": mem_cap,
                "status": "Ready" if conditions.get("Ready") else "NotReady",
                # 할당 가능 리소스
                "cpu_allocatable": cpu_alloc,
                "memory_allocatable_bytes": mem_alloc,
                # 요청 리소스
                "cpu_requested": cpu_req,
                "memory_requested_bytes": mem_req,
                # 실제 사용량 (metrics-server)
                "cpu_used": cpu_used,
                "memory_used_bytes": mem_used,
                # 사용률
                "cpu_request_ratio": round(cpu_req / cpu_alloc * 100, 2) if cpu_alloc else 0.0,
                "cpu_usage_ratio": round(cpu_used / cpu_alloc * 100, 2) if actual_usage_available and cpu_alloc else None,
                "memory_request_ratio": round(mem_req / mem_alloc * 100, 2) if mem_alloc else 0.0,
                "memory_usage_ratio": round(mem_used / mem_alloc * 100, 2) if actual_usage_available and mem_alloc else None,
                # 실제 사용량 가용 여부
                "actual_usage_available": actual_usage_available,
                # 파드 현황
                "pods_running": pods_on_node["running"],
                "pods_pending": pods_on_node["pending"],
                "pods_failed": pods_on_node["failed"],
                "pods_crash_loop": pods_on_node["crash_loop"],
                # 추가 조건 정보
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
                plural="nodes",
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
                logger.info("metrics-server not installed — using requests only")
                return {}
            logger.warning("metrics-server fetch failed: %s", e)
            return {}
        except Exception as e:
            logger.warning("Unexpected error fetching node metrics: %s", e)
            return {}

    def _collect_node_pods(self, node_name: str) -> dict:
        """특정 노드 위의 파드 상태를 집계한다."""
        summary = {"running": 0, "pending": 0, "failed": 0, "crash_loop": 0}
        try:
            pods = self.core_v1.list_pod_for_all_namespaces(
                field_selector=f"spec.nodeName={node_name}"
            )
            for pod in pods.items:
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
        except ApiException as e:
            logger.warning("Failed to list pods on node %s: %s", node_name, e)
        return summary

    # ------------------------------------------------------------------
    # 파드 요약
    # ------------------------------------------------------------------

    def _collect_pods_summary(self) -> dict:
        """전체 파드 상태 요약을 반환한다."""
        pods = self.core_v1.list_pod_for_all_namespaces()
        summary = {
            "total": 0,
            "running": 0,
            "pending": 0,
            "failed": 0,
            "crash_loop": 0,
        }

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

    # ------------------------------------------------------------------
    # 워크로드 수집
    # ------------------------------------------------------------------

    def _collect_workloads(self) -> dict:
        """Deployment, StatefulSet, DaemonSet 상태를 수집한다."""
        workloads = {
            "deployments_total": 0,
            "deployments_degraded": 0,
            "statefulsets_total": 0,
            "statefulsets_degraded": 0,
            "daemonsets_total": 0,
            "daemonsets_degraded": 0,
        }

        try:
            deployments = self.apps_v1.list_deployment_for_all_namespaces()
            workloads["deployments_total"] = len(deployments.items)
            workloads["deployments_degraded"] = sum(
                1 for d in deployments.items
                if (d.status.ready_replicas or 0) < (d.spec.replicas or 0)
            )
        except ApiException as e:
            logger.warning("Failed to list deployments: %s", e)

        try:
            statefulsets = self.apps_v1.list_stateful_set_for_all_namespaces()
            workloads["statefulsets_total"] = len(statefulsets.items)
            workloads["statefulsets_degraded"] = sum(
                1 for s in statefulsets.items
                if (s.status.ready_replicas or 0) < (s.spec.replicas or 1)
            )
        except ApiException as e:
            logger.warning("Failed to list statefulsets: %s", e)

        try:
            daemonsets = self.apps_v1.list_daemon_set_for_all_namespaces()
            workloads["daemonsets_total"] = len(daemonsets.items)
            workloads["daemonsets_degraded"] = sum(
                1 for ds in daemonsets.items
                if (ds.status.number_ready or 0) < (ds.status.desired_number_scheduled or 0)
            )
        except ApiException as e:
            logger.warning("Failed to list daemonsets: %s", e)

        return workloads

    # ------------------------------------------------------------------
    # 이벤트 수집
    # ------------------------------------------------------------------

    def _collect_events(self, minutes: int = 60) -> list[dict]:
        """최근 Warning 이벤트를 수집한다."""
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)

        try:
            events = self.core_v1.list_event_for_all_namespaces(
                field_selector="type=Warning"
            )
        except ApiException as e:
            logger.warning("Failed to list events: %s", e)
            return []

        result = []
        for ev in events.items:
            last_time = ev.last_timestamp
            if last_time:
                # last_timestamp는 timezone-aware datetime일 수 있음
                ts = last_time
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts > cutoff:
                    result.append({
                        "type": ev.reason,
                        "namespace": ev.metadata.namespace,
                        "object": (
                            f"{ev.involved_object.kind}/{ev.involved_object.name}"
                            if ev.involved_object else "unknown"
                        ),
                        "message": ev.message,
                        "count": ev.count,
                        "last_seen": ts.isoformat(),
                    })

        return result

    # ------------------------------------------------------------------
    # 파싱 유틸리티
    # ------------------------------------------------------------------

    def _parse_cpu(self, cpu_str: str) -> float:
        """'250m' → 0.25, '2' → 2.0 코어 단위로 변환한다."""
        if not cpu_str:
            return 0.0
        cpu_str = str(cpu_str).strip()
        if cpu_str.endswith("m"):
            return int(cpu_str[:-1]) / 1000
        try:
            return float(cpu_str)
        except ValueError:
            logger.warning("Cannot parse CPU value: %s", cpu_str)
            return 0.0

    def _parse_memory(self, mem_str: str) -> int:
        """'512Mi' → bytes 변환한다."""
        if not mem_str:
            return 0
        mem_str = str(mem_str).strip()
        units = {
            "Ki": 1024,
            "Mi": 1024 ** 2,
            "Gi": 1024 ** 3,
            "Ti": 1024 ** 4,
            "K": 1000,
            "M": 1000 ** 2,
            "G": 1000 ** 3,
            "T": 1000 ** 4,
        }
        for suffix, mult in units.items():
            if mem_str.endswith(suffix):
                try:
                    return int(mem_str[: -len(suffix)]) * mult
                except ValueError:
                    logger.warning("Cannot parse memory value: %s", mem_str)
                    return 0
        try:
            return int(mem_str)
        except ValueError:
            logger.warning("Cannot parse memory value: %s", mem_str)
            return 0

    def _sum_node_requests(self, node_name: str) -> tuple[float, int]:
        """특정 노드의 모든 Running 파드 CPU/Memory requests 합계를 반환한다."""
        try:
            pods = self.core_v1.list_pod_for_all_namespaces(
                field_selector=f"spec.nodeName={node_name},status.phase=Running"
            )
        except ApiException as e:
            logger.warning("Failed to list pods for node %s: %s", node_name, e)
            return 0.0, 0

        cpu_total, mem_total = 0.0, 0
        for pod in pods.items:
            for container in pod.spec.containers:
                req = {}
                if container.resources and container.resources.requests:
                    req = container.resources.requests
                cpu_total += self._parse_cpu(req.get("cpu", "0"))
                mem_total += self._parse_memory(req.get("memory", "0"))

        return cpu_total, mem_total
