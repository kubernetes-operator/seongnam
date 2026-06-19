"""리포트 엔드포인트."""
import asyncio
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from api.dependencies import get_pool, verify_api_key
from api.models import ApiResponse, ReportGenerateRequest

router = APIRouter()


@router.get("", dependencies=[Depends(verify_api_key)])
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


@router.get("/{report_id}", dependencies=[Depends(verify_api_key)])
async def get_report(report_id: str, pool=Depends(get_pool)):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM reports WHERE file_path LIKE $1 ORDER BY created_at DESC LIMIT 1",
            f"%{report_id}%",
        )
    if not row:
        raise HTTPException(status_code=404, detail="Report not found")
    return ApiResponse.ok(dict(row))


@router.get("/{report_id}/download", dependencies=[Depends(verify_api_key)])
async def download_report(report_id: str, fmt: str = Query("html"), pool=Depends(get_pool)):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT file_path FROM reports WHERE file_path LIKE $1 AND format = $2 ORDER BY created_at DESC LIMIT 1",
            f"%{report_id}%",
            fmt,
        )
    if not row or not row["file_path"]:
        raise HTTPException(status_code=404, detail="Report file not found")
    return FileResponse(row["file_path"])


@router.post("/generate", dependencies=[Depends(verify_api_key)])
async def generate_report(req: ReportGenerateRequest, pool=Depends(get_pool)):
    from reports.generator import ReportGenerator
    generator = ReportGenerator(pool)

    async def _run():
        return await generator.generate(
            req.report_type, req.cluster_name, req.output_formats
        )

    # 백그라운드 태스크로 실행
    task = asyncio.create_task(_run())

    async def _background():
        try:
            await task
        except Exception:
            pass

    asyncio.ensure_future(_background())
    return ApiResponse.ok({"status": "generating", "cluster": req.cluster_name, "type": req.report_type})
