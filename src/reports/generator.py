"""일간/주간/월간/연간 리포트 생성."""
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

REPORT_DIR = os.environ.get("REPORT_DIR", "/reports")

REPORT_CONFIGS = {
    "daily":   {"interval": "1h",  "days": 1},
    "weekly":  {"interval": "1d",  "days": 7},
    "monthly": {"interval": "1d",  "days": 30},
    "yearly":  {"interval": "7d",  "days": 365},
}


class ReportGenerator:
    def __init__(self, pool, predictor=None):
        self.pool = pool
        self.predictor = predictor

    async def generate(
        self,
        report_type: str,
        cluster_name: str,
        output_formats: list[str] = ("json", "html"),
        period_start: datetime = None,
        period_end: datetime = None,
    ) -> dict:
        cfg = REPORT_CONFIGS[report_type]
        if not period_end:
            period_end = datetime.now(timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        if not period_start:
            period_start = period_end - timedelta(days=cfg["days"])

        data = await self._collect_data(cluster_name, period_start, period_end, cfg["interval"])

        if report_type in ("monthly", "yearly") and self.predictor:
            try:
                data["predictions"] = await self.predictor.run_prediction(self.pool)
            except Exception:
                data["predictions"] = None

        report_id = f"{report_type}-{period_start.strftime('%Y%m%d')}-{cluster_name}"
        Path(REPORT_DIR).mkdir(parents=True, exist_ok=True)
        files = {}

        for fmt in output_formats:
            path = await self._write_report(report_id, fmt, data)
            files[fmt] = path

        from db.queries import insert_report_record
        await insert_report_record(
            self.pool,
            report_type=report_type,
            cluster_name=cluster_name,
            period_start=period_start,
            period_end=period_end,
            files=files,
            summary=data.get("summary", {}),
        )

        return {"report_id": report_id, "files": files, "summary": data.get("summary", {})}

    async def _collect_data(
        self, cluster_name: str, start: datetime, end: datetime, interval: str
    ) -> dict:
        from db.queries import (
            query_metric_timeseries, query_top_nodes, query_events,
            query_latest_metrics, query_latest_k8s_metrics,
        )

        # 노드 목록
        async with self.pool.acquire() as conn:
            nodes = await conn.fetch(
                "SELECT node_name, node_ip, cpu_cores FROM cluster_nodes WHERE cluster_name = $1",
                cluster_name,
            )

        node_os_data = {}
        for node in nodes:
            nm = node["node_name"]
            metrics = {}
            for metric in ["cpu_usage_ratio", "memory_usage_ratio", "disk_usage_ratio", "load1"]:
                ts = await query_metric_timeseries(
                    self.pool, cluster_name, nm, metric,
                    start.isoformat(), end.isoformat(), interval
                )
                metrics[metric] = ts
            node_os_data[nm] = metrics

        top_cpu  = await query_top_nodes(self.pool, cluster_name, "cpu_usage_ratio",    5)
        top_mem  = await query_top_nodes(self.pool, cluster_name, "memory_usage_ratio", 5)
        top_disk = await query_top_nodes(self.pool, cluster_name, "disk_usage_ratio",   5)
        events   = await query_events(self.pool, cluster_name, limit=100)

        summary = {
            "cluster_name": cluster_name,
            "period_start": start.isoformat(),
            "period_end":   end.isoformat(),
            "nodes_total":  len(nodes),
            "alerts_total": len(events),
            "top_cpu_node": top_cpu[0]["node_name"] if top_cpu else None,
            "top_cpu_ratio": top_cpu[0].get("avg_value") if top_cpu else None,
        }

        return {
            "summary": summary,
            "node_os_metrics": node_os_data,
            "top_nodes": {"cpu": top_cpu, "memory": top_mem, "disk": top_disk},
            "events": [dict(e) for e in events[:50]],
        }

    async def _write_report(self, report_id: str, fmt: str, data: dict) -> str:
        path = f"{REPORT_DIR}/{report_id}.{fmt}"

        if fmt == "json":
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)

        elif fmt == "html":
            html = self._render_html(data)
            with open(path, "w", encoding="utf-8") as f:
                f.write(html)

        logger.info("리포트 생성: %s", path)
        return path

    def _render_html(self, data: dict) -> str:
        summary = data.get("summary", {})
        events = data.get("events", [])
        top_cpu = data.get("top_nodes", {}).get("cpu", [])

        rows = "".join(
            f"<tr><td>{e.get('time','')}</td><td>{e.get('severity','')}</td>"
            f"<td>{e.get('node_name','')}</td><td>{e.get('message','')}</td></tr>"
            for e in events[:20]
        )
        top_rows = "".join(
            f"<tr><td>{n['node_name']}</td><td>{n.get('avg_value',0):.1f}%</td>"
            f"<td>{n.get('max_value',0):.1f}%</td></tr>"
            for n in top_cpu
        )

        return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>K8s Monitor Report — {summary.get('cluster_name','')} {summary.get('period_start','')[:10]}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
  body {{ font-family: sans-serif; max-width: 1200px; margin: 0 auto; padding: 1rem; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ border: 1px solid #ccc; padding: 6px 10px; text-align: left; }}
  th {{ background: #f4f4f4; }}
  .critical {{ color: #c0392b; }}
  .warning  {{ color: #e67e22; }}
  h2 {{ border-bottom: 2px solid #3498db; padding-bottom: 4px; }}
</style>
</head>
<body>
<h1>K8s OS Monitor 리포트</h1>
<p><b>클러스터:</b> {summary.get('cluster_name','')} &nbsp;
   <b>기간:</b> {summary.get('period_start','')[:10]} ~ {summary.get('period_end','')[:10]}</p>

<h2>요약</h2>
<ul>
  <li>총 노드: <b>{summary.get('nodes_total',0)}</b></li>
  <li>총 이벤트: <b>{summary.get('alerts_total',0)}</b></li>
  <li>최고 CPU 노드: <b>{summary.get('top_cpu_node','N/A')}</b>
      ({summary.get('top_cpu_ratio') or 'N/A'}%)</li>
</ul>

<h2>Top CPU 노드</h2>
<table>
  <tr><th>노드</th><th>평균</th><th>최대</th></tr>
  {top_rows}
</table>

<h2>이벤트 목록</h2>
<table>
  <tr><th>시각</th><th>심각도</th><th>노드</th><th>메시지</th></tr>
  {rows}
</table>
</body>
</html>"""
