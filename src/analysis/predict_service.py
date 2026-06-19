"""예측 서비스 — 1일 1회 배치 실행."""
import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

CLUSTER_NAME = os.environ.get("CLUSTER_NAME", "playce-k8s")


async def run_prediction(pool) -> dict:
    from analysis.predictor import TrendPredictor
    from db.queries import query_metric_timeseries, query_clusters, insert_event

    predictor = TrendPredictor()
    clusters = await query_clusters(pool)
    if not clusters:
        clusters = [{"cluster_name": CLUSTER_NAME}]

    all_predictions = []

    for cluster in clusters:
        cluster_name = cluster["cluster_name"]
        now = datetime.now(timezone.utc)
        start = (now - timedelta(days=30)).isoformat()
        end = now.isoformat()

        metrics_to_predict = ["cpu_usage_ratio", "memory_usage_ratio", "disk_usage_ratio"]

        # 노드 목록 조회
        async with pool.acquire() as conn:
            nodes = await conn.fetch(
                "SELECT DISTINCT node_name FROM cluster_nodes WHERE cluster_name = $1",
                cluster_name,
            )

        node_predictions = []
        for node_row in nodes:
            node_name = node_row["node_name"]
            node_preds = {}
            for metric in metrics_to_predict:
                try:
                    ts = await query_metric_timeseries(
                        pool, cluster_name, node_name, metric, start, end, interval="1d"
                    )
                    pred = predictor.predict_metric(ts, horizon_days=90, metric_name=metric)
                    node_preds[metric] = pred
                except Exception as e:
                    logger.warning("예측 실패 %s/%s/%s: %s", cluster_name, node_name, metric, e)

            node_predictions.append({"node_name": node_name, "predictions": node_preds})

        recs = predictor.generate_recommendations(cluster_name, node_predictions)

        # 긴급 권고는 이벤트로 기록
        for rec in recs:
            if rec.get("urgency") == "high":
                await insert_event(pool, {
                    "cluster_name": cluster_name,
                    "node_name": rec.get("node"),
                    "event_type": "prediction",
                    "severity": "warning",
                    "message": rec["recommendation"],
                    "details": rec,
                })

        all_predictions.append({
            "cluster_name": cluster_name,
            "predicted_at": now.isoformat(),
            "nodes": node_predictions,
            "recommendations": recs,
        })

    logger.info("예측 완료: %d 클러스터", len(all_predictions))
    return {"predictions": all_predictions}


async def run_service() -> None:
    from db.pool import get_pool
    pool = await get_pool()

    while True:
        try:
            await run_prediction(pool)
        except Exception as e:
            logger.error("예측 서비스 오류: %s", e)
        await asyncio.sleep(86400)  # 24시간마다 실행


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(run_service())
