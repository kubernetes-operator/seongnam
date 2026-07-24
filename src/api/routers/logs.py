"""Linux 시스템 로그(systemd journal via Loki) 조회·분석 엔드포인트."""
from typing import Optional

from fastapi import APIRouter, Depends, Query

from api.dependencies import verify_api_key
from api.models import ApiResponse

router = APIRouter()


@router.get("", dependencies=[Depends(verify_api_key)])
async def list_logs(
    node_name: Optional[str] = Query(None),
    priority: Optional[str] = Query(None, description="emerg/alert/crit/error/warning/notice/info/debug"),
    q: Optional[str] = Query(None, description="본문 검색어(대소문자 무시)"),
    minutes: int = Query(60, ge=1, le=10080),
    limit: int = Query(100, ge=1, le=1000),
):
    from analysis.log_service import recent_logs
    lines = await recent_logs(node_name or "", priority or "", q or "", minutes, limit)
    return ApiResponse.ok(lines, meta={"total": len(lines), "window_minutes": minutes})


@router.get("/summary", dependencies=[Depends(verify_api_key)])
async def logs_summary(minutes: int = Query(60, ge=1, le=10080)):
    from analysis.log_service import summary
    return ApiResponse.ok(await summary(minutes))


@router.get("/patterns", dependencies=[Depends(verify_api_key)])
async def logs_patterns(
    node_name: Optional[str] = Query(None),
    minutes: int = Query(60, ge=1, le=10080),
):
    from analysis.log_service import detect_patterns
    patterns = await detect_patterns(node_name or "", minutes)
    return ApiResponse.ok(patterns, meta={"total": len(patterns)})
