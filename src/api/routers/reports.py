"""리포트 엔드포인트."""
import os
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from api.dependencies import get_pool, verify_session
from api.models import ApiResponse, ReportGenerateRequest

router = APIRouter()

_MEDIA = {"html": "text/html; charset=utf-8", "json": "application/json; charset=utf-8"}


@router.get("", dependencies=[Depends(verify_session)])
async def list_reports(
    report_type: Optional[str] = Query(None),
    cluster_name: Optional[str] = Query(None),
    page: int = Query(1),
    size: int = Query(20),
    pool=Depends(get_pool),
):
    conditions = []
    params = []
    if report_type:
        params.append(report_type)
        conditions.append(f"report_type = ${len(params)}")
    if cluster_name:
        params.append(cluster_name)
        conditions.append(f"cluster_name = ${len(params)}")
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    offset = (page - 1) * size

    sql = f"SELECT * FROM reports {where} ORDER BY created_at DESC LIMIT {size} OFFSET {offset}"
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)
        count_row = await conn.fetchrow(f"SELECT count(*) FROM reports {where}", *params)

    return ApiResponse.ok(
        [dict(r) for r in rows],
        meta={"total": count_row[0], "page": page, "size": size},
    )


@router.get("/{report_id}", dependencies=[Depends(verify_session)])
async def get_report(report_id: str, pool=Depends(get_pool)):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM reports WHERE file_path LIKE $1 ORDER BY created_at DESC LIMIT 1",
            f"%{report_id}%",
        )
    if not row:
        raise HTTPException(status_code=404, detail="Report not found")
    return ApiResponse.ok(dict(row))


async def _fetch_report_row(pool, report_id: str):
    """report_id 가 숫자면 id 로, 아니면 file_path LIKE 로 조회."""
    async with pool.acquire() as conn:
        if str(report_id).isdigit():
            return await conn.fetchrow(
                "SELECT format, file_path, content FROM reports WHERE id = $1", int(report_id)
            )
        return await conn.fetchrow(
            "SELECT format, file_path, content FROM reports WHERE file_path LIKE $1 ORDER BY created_at DESC LIMIT 1",
            f"%{report_id}%",
        )


def _serve(row, inline: bool):
    """DB content 우선, 없으면 파일. inline 이면 브라우저 표시용, 아니면 첨부(다운로드)."""
    fmt = row["format"]
    media = _MEDIA.get(fmt, "application/octet-stream")
    disp = "inline" if inline else "attachment"
    fname = f"report.{fmt}"
    if row["content"]:
        return Response(
            content=row["content"], media_type=media,
            headers={"Content-Disposition": f'{disp}; filename="{fname}"'},
        )
    if row["file_path"] and os.path.exists(row["file_path"]):
        return FileResponse(row["file_path"], media_type=media, filename=None if inline else fname)
    raise HTTPException(status_code=404, detail="리포트 내용을 찾을 수 없습니다 (재생성이 필요할 수 있습니다)")


@router.get("/{report_id}/download", dependencies=[Depends(verify_session)])
async def download_report(report_id: str, pool=Depends(get_pool)):
    row = await _fetch_report_row(pool, report_id)
    if not row:
        raise HTTPException(status_code=404, detail="Report not found")
    return _serve(row, inline=False)


@router.get("/{report_id}/view", dependencies=[Depends(verify_session)])
async def view_report(report_id: str, pool=Depends(get_pool)):
    row = await _fetch_report_row(pool, report_id)
    if not row:
        raise HTTPException(status_code=404, detail="Report not found")
    return _serve(row, inline=True)


@router.post("/generate", dependencies=[Depends(verify_session)])
async def generate_report(req: ReportGenerateRequest, pool=Depends(get_pool)):
    import logging
    from reports.generator import ReportGenerator
    logger = logging.getLogger(__name__)
    generator = ReportGenerator(pool)
    try:
        result = await generator.generate(
            req.report_type, req.cluster_name, req.output_formats
        )
        return ApiResponse.ok(result)
    except Exception as e:
        logger.error("리포트 생성 실패: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
