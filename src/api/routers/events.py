"""위기 이벤트 엔드포인트."""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from api.dependencies import get_pool, verify_api_key
from api.models import ApiResponse

router = APIRouter()


@router.get("", dependencies=[Depends(verify_api_key)])
async def list_events(
    cluster_name: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    resolved: bool = Query(False),
    limit: int = Query(50),
    pool=Depends(get_pool),
):
    from db.queries import query_events
    events = await query_events(pool, cluster_name or "", severity, resolved, limit)
    return ApiResponse.ok(events, meta={"total": len(events)})


@router.get("/{event_id}", dependencies=[Depends(verify_api_key)])
async def get_event(event_id: int, pool=Depends(get_pool)):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM events WHERE id = $1", event_id)
    if not row:
        raise HTTPException(status_code=404, detail="Event not found")
    ev = dict(row)
    # 위기 유형에 맞는 카탈로그 정보 추가
    if ev.get("details"):
        import json
        details = json.loads(ev["details"]) if isinstance(ev["details"], str) else ev["details"]
        crisis_type = details.get("crisis_type", "")
        from analysis.crisis_catalog import CRISIS_CATALOG
        ev["catalog"] = CRISIS_CATALOG.get(crisis_type, {})
    return ApiResponse.ok(ev)


@router.patch("/{event_id}/resolve", dependencies=[Depends(verify_api_key)])
async def resolve_event(event_id: int, pool=Depends(get_pool)):
    from db.queries import resolve_event as _resolve
    ok = await _resolve(pool, event_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Event not found or already resolved")
    return ApiResponse.ok({"resolved": True, "event_id": event_id})
