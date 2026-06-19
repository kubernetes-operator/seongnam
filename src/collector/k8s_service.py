"""K8s 수집기 서비스 루프.

60초마다 K8sMetricsCollector.collect_all()을 실행하고,
수집 결과를 TimescaleDB k8s_metrics 테이블에 적재한다.
NotReady 노드, CrashLoop 파드, OOMKilled 이벤트를 감지하면
events 테이블에도 기록한다.

환경변수:
    CLUSTER_NAME: 클러스터 식별명 (기본값: playce-k8s)
    DATABASE_URL: TimescaleDB 접속 DSN
"""
import asyncio
import logging
import os
import sys

logger = logging.getLogger(__name__)

CLUSTER_NAME = os.environ.get("CLUSTER_NAME", "playce-k8s")
COLLECT_INTERVAL = int(os.environ.get("COLLECT_INTERVAL", "60"))


async def run_service() -> None:
    """K8s 수집 서비스 메인 루프."""
    sys.path.insert(0, "/app")

    from collector.k8s_collector import K8sMetricsCollector
    from db.pool import get_pool
    from db.queries import insert_k8s_metrics, insert_event, upsert_cluster_node

    pool = await get_pool()
    collector = K8sMetricsCollector()

    logger.info(
        "K8s collector started — cluster=%s, interval=%ds",
        CLUSTER_NAME,
        COLLECT_INTERVAL,
    )

    while True:
        try:
            await _collect_and_store(collector, pool, CLUSTER_NAME,
                                     insert_k8s_metrics, insert_event, upsert_cluster_node)
        except Exception as e:
            logger.error("K8s collection cycle failed: %s", e, exc_info=True)

        await asyncio.sleep(COLLECT_INTERVAL)


async def _collect_and_store(
    collector,
    pool,
    cluster_name: str,
    insert_k8s_metrics,
    insert_event,
    upsert_cluster_node,
) -> None:
    """한 번의 수집 사이클을 수행한다."""
    data = collector.collect_all(cluster_name)
    collected_at = data["collected_at"]
    nodes = data.get("nodes", [])
    pods_summary = data.get("pods_summary", {})
    recent_warnings = data.get("recent_warnings", [])

    records = []

    for node in nodes:
        node_name = node["name"]

        # cluster_nodes 레지스트리 upsert (OS/커널/역할/용량 포함)
        try:
            await upsert_cluster_node(
                pool,
                cluster_name,
                node_name,
                node.get("node_ip", ""),
                role=node.get("role"),
                os_distro=node.get("os_distro"),
                kernel_version=node.get("kernel_version"),
                cpu_cores=node.get("cpu_cores"),
                memory_total_bytes=node.get("memory_total_bytes"),
            )
        except Exception as e:
            logger.warning("upsert_cluster_node failed for %s: %s", node_name, e)

        # k8s_metrics 레코드 구성
        records.append({
            "time": collected_at,
            "cluster_name": cluster_name,
            "node_name": node_name,
            "node_status": node.get("status"),
            "cpu_allocatable": node.get("cpu_allocatable"),
            "cpu_requested": node.get("cpu_requested"),
            "cpu_used": node.get("cpu_used"),
            "cpu_request_ratio": node.get("cpu_request_ratio"),
            "cpu_usage_ratio": node.get("cpu_usage_ratio"),
            "memory_allocatable_bytes": node.get("memory_allocatable_bytes"),
            "memory_requested_bytes": node.get("memory_requested_bytes"),
            "memory_used_bytes": node.get("memory_used_bytes"),
            "memory_request_ratio": node.get("memory_request_ratio"),
            "memory_usage_ratio": node.get("memory_usage_ratio"),
            "pods_running": node.get("pods_running", 0),
            "pods_pending": node.get("pods_pending", 0),
            "pods_failed": node.get("pods_failed", 0),
            "pods_crash_loop": node.get("pods_crash_loop", 0),
            "actual_usage_available": node.get("actual_usage_available", False),
        })

        # NotReady 노드 감지 → events 테이블 기록
        if node.get("status") == "NotReady":
            try:
                await insert_event(pool, {
                    "cluster_name": cluster_name,
                    "node_name": node_name,
                    "event_type": "k8s_alert",
                    "severity": "critical",
                    "message": f"NODE_NOT_READY: {node_name}",
                    "details": {
                        "crisis_type": "NODE_NOT_READY",
                        "node": node_name,
                        "conditions": node.get("conditions", {}),
                    },
                })
                logger.warning("ALERT: Node %s is NotReady", node_name)
            except Exception as e:
                logger.error("insert_event (NotReady) failed: %s", e)

        # 노드별 CrashLoop 파드 감지
        crash_count = node.get("pods_crash_loop", 0)
        if crash_count > 0:
            try:
                await insert_event(pool, {
                    "cluster_name": cluster_name,
                    "node_name": node_name,
                    "event_type": "k8s_alert",
                    "severity": "warning",
                    "message": f"CRASHLOOP_BACKOFF: {crash_count} pods on {node_name}",
                    "details": {
                        "crisis_type": "CRASHLOOP_BACKOFF",
                        "node": node_name,
                        "count": crash_count,
                    },
                })
            except Exception as e:
                logger.error("insert_event (CrashLoop/node) failed: %s", e)

    # 클러스터 전체 CrashLoop 감지 (전체 파드 요약 기준)
    total_crash = pods_summary.get("crash_loop", 0)
    if total_crash > 0:
        try:
            await insert_event(pool, {
                "cluster_name": cluster_name,
                "node_name": None,
                "event_type": "k8s_alert",
                "severity": "warning",
                "message": f"CRASHLOOP_BACKOFF: {total_crash} pods in cluster",
                "details": {
                    "crisis_type": "CRASHLOOP_BACKOFF",
                    "count": total_crash,
                    "pods_summary": pods_summary,
                },
            })
        except Exception as e:
            logger.error("insert_event (CrashLoop/cluster) failed: %s", e)

    # OOMKilled 이벤트 감지
    for warning in recent_warnings:
        msg = (warning.get("message") or "").lower()
        reason = (warning.get("type") or "").lower()
        if "oomkill" in reason or "oomkill" in msg:
            try:
                await insert_event(pool, {
                    "cluster_name": cluster_name,
                    "node_name": None,
                    "event_type": "k8s_alert",
                    "severity": "critical",
                    "message": f"OOM_KILLED: {warning.get('object', 'unknown')}",
                    "details": {
                        "crisis_type": "OOM_KILLED",
                        "object": warning.get("object"),
                        "namespace": warning.get("namespace"),
                        "count": warning.get("count"),
                        "last_seen": warning.get("last_seen"),
                        "message": warning.get("message"),
                    },
                })
                logger.warning(
                    "ALERT: OOMKilled detected — %s", warning.get("object")
                )
            except Exception as e:
                logger.error("insert_event (OOMKilled) failed: %s", e)

    # k8s_metrics 배치 삽입
    if records:
        try:
            await insert_k8s_metrics(pool, records)
            logger.info(
                "K8s metrics inserted: cluster=%s, nodes=%d, pods_summary=%s",
                cluster_name,
                len(records),
                pods_summary,
            )
        except Exception as e:
            logger.error("insert_k8s_metrics failed: %s", e)
    else:
        logger.warning("No node records to insert for cluster=%s", cluster_name)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(run_service())
