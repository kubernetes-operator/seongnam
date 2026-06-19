"""메트릭 조회 엔드포인트."""
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, Query
from api.dependencies import get_pool, verify_api_key
from api.models import ApiResponse

router = APIRouter()


@router.get("/os/{cluster_name}/{node_name}", dependencies=[Depends(verify_api_key)])
async def get_os_metrics(
    cluster_name: str,
    node_name: str,
    metric: str = Query("cpu_usage_ratio"),
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    interval: str = Query("1h"),
    pool=Depends(get_pool),
):
    from db.queries import query_metric_timeseries
    if not end:
        end = datetime.now(timezone.utc).isoformat()
    if not start:
        start = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    ts = await query_metric_timeseries(pool, cluster_name, node_name, metric, start, end, interval)
    return ApiResponse.ok(ts, meta={"cluster": cluster_name, "node": node_name, "metric": metric})


@router.get("/k8s/{cluster_name}/{node_name}", dependencies=[Depends(verify_api_key)])
async def get_k8s_metrics(
    cluster_name: str,
    node_name: str,
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    interval: str = Query("1h"),
    pool=Depends(get_pool),
):
    from db.queries import query_metric_timeseries
    if not end:
        end = datetime.now(timezone.utc).isoformat()
    if not start:
        start = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    ts = await query_metric_timeseries(pool, cluster_name, node_name, "cpu_usage_ratio", start, end, interval)
    return ApiResponse.ok(ts, meta={"cluster": cluster_name, "node": node_name})


@router.get("/summary/{cluster_name}", dependencies=[Depends(verify_api_key)])
async def get_summary(cluster_name: str, pool=Depends(get_pool)):
    from db.queries import query_latest_metrics, query_latest_k8s_metrics
    os_m  = await query_latest_metrics(pool, cluster_name)
    k8s_m = await query_latest_k8s_metrics(pool, cluster_name)
    return ApiResponse.ok({"cluster": cluster_name, "os": os_m, "k8s": k8s_m})


@router.get("/top", dependencies=[Depends(verify_api_key)])
async def get_top_nodes(
    cluster_name: str = Query(...),
    metric: str = Query("cpu_usage_ratio"),
    limit: int = Query(5),
    pool=Depends(get_pool),
):
    from db.queries import query_top_nodes
    top = await query_top_nodes(pool, cluster_name, metric, limit)
    return ApiResponse.ok(top)
