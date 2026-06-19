"""클러스터 관련 엔드포인트."""
from fastapi import APIRouter, Depends
from api.dependencies import get_pool, verify_api_key
from api.models import ApiResponse

router = APIRouter()


@router.get("", dependencies=[Depends(verify_api_key)])
async def list_clusters(pool=Depends(get_pool)):
    from db.queries import query_clusters
    clusters = await query_clusters(pool)
    return ApiResponse.ok(clusters)


@router.get("/{cluster_name}", dependencies=[Depends(verify_api_key)])
async def get_cluster(cluster_name: str, pool=Depends(get_pool)):
    from db.queries import query_latest_metrics, query_latest_k8s_metrics, query_events
    os_metrics  = await query_latest_metrics(pool, cluster_name)
    k8s_metrics = await query_latest_k8s_metrics(pool, cluster_name)
    events      = await query_events(pool, cluster_name, resolved=False, limit=10)
    return ApiResponse.ok({
        "cluster_name": cluster_name,
        "os_metrics":   os_metrics,
        "k8s_metrics":  k8s_metrics,
        "active_events": len(events),
    })


@router.get("/{cluster_name}/nodes", dependencies=[Depends(verify_api_key)])
async def list_nodes(cluster_name: str, pool=Depends(get_pool)):
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM cluster_nodes WHERE cluster_name = $1 ORDER BY node_name",
            cluster_name,
        )
    return ApiResponse.ok([dict(r) for r in rows])
