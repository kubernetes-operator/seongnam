"""OS 수집기 서비스 루프."""
import asyncio
import logging
import os

logger = logging.getLogger(__name__)

CLUSTER_NAME = os.environ.get("CLUSTER_NAME", "playce-k8s")

THRESHOLDS = {
    "cpu_usage_ratio":    {"warning": 80.0, "critical": 90.0, "type": "HIGH_CPU"},
    "memory_usage_ratio": {"warning": 80.0, "critical": 90.0, "type": "MEMORY_EXHAUSTION"},
    "disk_usage_ratio":   {"warning": 75.0, "critical": 90.0, "type": "DISK_FULL"},
    "load_per_core":      {"warning": 1.5,  "critical": 2.0,  "type": "HIGH_LOAD"},
}


def check_thresholds(node_data: dict) -> list[dict]:
    flat = {
        "cpu_usage_ratio":    node_data.get("cpu", {}).get("usage_ratio"),
        "memory_usage_ratio": node_data.get("memory", {}).get("usage_ratio"),
        "disk_usage_ratio":   node_data.get("disk", {}).get("usage_ratio"),
        "load_per_core":      node_data.get("load", {}).get("load_per_core"),
    }
    alerts = []
    for metric, limits in THRESHOLDS.items():
        value = flat.get(metric)
        if value is None:
            continue
        if value >= limits["critical"]:
            alerts.append({"crisis_type": limits["type"], "metric": metric, "value": value, "severity": "critical"})
        elif value >= limits["warning"]:
            alerts.append({"crisis_type": limits["type"], "metric": metric, "value": value, "severity": "warning"})
    return alerts


async def run_service() -> None:
    from collector.os_collector import PrometheusCollector
    from db.pool import get_pool
    from db.queries import insert_os_metrics, insert_event, upsert_cluster_node
    from db.schema import init_schema

    pool = await get_pool()
    # API 보다 먼저 떠도 새 컬럼(inode_usage_ratio, uptime_sec)이 있도록 멱등 스키마 적용
    try:
        await init_schema(pool)
    except Exception as e:
        logger.warning("스키마 적용 실패(계속 진행): %s", e)
    collector = PrometheusCollector()

    while True:
        try:
            data = await collector.collect_all(CLUSTER_NAME)

            records = []
            for nm in data["node_metrics"]:
                if nm.get("collection_status") == "failed":
                    continue

                records.append(nm)

                await upsert_cluster_node(
                    pool,
                    CLUSTER_NAME,
                    nm["node_name"],
                    nm.get("node_ip", ""),
                    cpu_cores=nm["cpu"].get("cores"),
                    # 코어 수·OS·커널 모두 Prometheus(Node Exporter) 지표에서 가져온다 (SSH 미사용)
                    os_distro=nm.get("os_distro"),
                    kernel_version=nm.get("kernel_version"),
                )

                for alert in check_thresholds(nm):
                    await insert_event(pool, {
                        "cluster_name": CLUSTER_NAME,
                        "node_name": nm["node_name"],
                        "event_type": "os_alert",
                        "severity": alert["severity"],
                        "message": f"{alert['crisis_type']}: {alert['metric']}={alert['value']:.1f}",
                        "details": alert,
                    })

            if records:
                inserted = await insert_os_metrics(pool, records)
                logger.info("수집 완료: %d노드, %d건 적재", len(records), inserted)

        except Exception as e:
            logger.error("수집 사이클 오류: %s", e)

        await asyncio.sleep(60)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    asyncio.run(run_service())
