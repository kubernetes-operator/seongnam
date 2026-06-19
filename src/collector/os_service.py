"""OS 수집기 서비스 루프."""
import asyncio
import logging
import os
import sys

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
    from collector.os_collector import PrometheusCollector, NODE_IP_MAP
    from collector.os_ssh import supplement_all
    from db.pool import get_pool
    from db.queries import insert_os_metrics, insert_event, upsert_cluster_node

    pool = await get_pool()
    collector = PrometheusCollector()
    ssh_cycle = 0

    while True:
        try:
            data = await collector.collect_all(CLUSTER_NAME)
            ssh_suppl = {}
            if ssh_cycle % 5 == 0:
                ssh_suppl = await supplement_all(NODE_IP_MAP)

            records = []
            for nm in data["node_metrics"]:
                if nm.get("collection_status") == "failed":
                    continue

                supp = ssh_suppl.get(nm["node_name"], {})
                cores = supp.get("cpu_cores")
                if cores and cores > 0:
                    nm["load"]["load_per_core"] = round(nm["load"]["load1"] / cores, 2)
                    nm["cpu"]["cores"] = cores

                records.append(nm)

                await upsert_cluster_node(
                    pool,
                    CLUSTER_NAME,
                    nm["node_name"],
                    nm.get("node_ip", ""),
                    cpu_cores=cores,
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

        ssh_cycle += 1
        await asyncio.sleep(60)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    asyncio.run(run_service())
