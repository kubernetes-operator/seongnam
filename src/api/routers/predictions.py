"""예측 데이터 엔드포인트."""
from typing import Optional
from fastapi import APIRouter, Depends, Query
from api.dependencies import get_pool, verify_api_key
from api.models import ApiResponse

router = APIRouter()


@router.get("/{cluster_name}", dependencies=[Depends(verify_api_key)])
async def get_cluster_predictions(
    cluster_name: str,
    horizon: int = Query(30),
    pool=Depends(get_pool),
):
    from analysis.predict_service import run_prediction
    result = await run_prediction(pool)
    cluster_preds = next(
        (p for p in result.get("predictions", []) if p["cluster_name"] == cluster_name),
        {"cluster_name": cluster_name, "nodes": [], "recommendations": []},
    )
    return ApiResponse.ok(cluster_preds)


@router.get("/{cluster_name}/{node_name}", dependencies=[Depends(verify_api_key)])
async def get_node_predictions(
    cluster_name: str,
    node_name: str,
    metric: Optional[str] = Query(None),
    pool=Depends(get_pool),
):
    from datetime import datetime, timezone, timedelta
    from db.queries import query_metric_timeseries
    from analysis.predictor import TrendPredictor

    predictor = TrendPredictor()
    metrics = [metric] if metric else ["cpu_usage_ratio", "memory_usage_ratio", "disk_usage_ratio"]
    end = datetime.now(timezone.utc).isoformat()
    start = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

    preds = {}
    for m in metrics:
        ts = await query_metric_timeseries(pool, cluster_name, node_name, m, start, end, "1d")
        preds[m] = predictor.predict_metric(ts, metric_name=m)

    return ApiResponse.ok({"cluster": cluster_name, "node": node_name, "predictions": preds})
