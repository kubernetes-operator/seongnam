---
name: report-builder
description: |
  일간/주간/월간/연간 모니터링 리포트를 Python으로 생성한다. JSON 데이터 집계, Jinja2 HTML 템플릿, Chart.js 그래프, WeasyPrint PDF 변환을 포함한다. 클러스터/노드별, OS/K8s 영역별로 구분하며 최대 대비 비율을 시각화한다. '리포트 생성', '일간 리포트', '주간 리포트', 'HTML 리포트', 'PDF 리포트', '사용량 보고서' 관련 구현 시 반드시 이 스킬을 사용할 것.
---

# Report Builder 스킬

## 리포트 생성 파이프라인

```python
# report_generator.py
from datetime import datetime, timezone, timedelta
from jinja2 import Environment, FileSystemLoader
import json, os

class ReportGenerator:
    """일/주/월/연간 리포트를 생성한다."""

    REPORT_CONFIGS = {
        "daily":   {"interval": "1h",  "days": 1},
        "weekly":  {"interval": "1d",  "days": 7},
        "monthly": {"interval": "1d",  "days": 30},
        "yearly":  {"interval": "7d",  "days": 365},
    }

    def __init__(self, db, predictor=None):
        self.db = db          # db-operations 모듈
        self.predictor = predictor
        self.jinja_env = Environment(
            loader=FileSystemLoader("templates/"),
            autoescape=True
        )

    async def generate(
        self,
        report_type: str,
        cluster_name: str,
        output_formats: list[str] = ("json", "html"),
        period_start: datetime = None,
        period_end: datetime = None,
    ) -> dict:
        """리포트를 생성하고 파일 경로를 반환한다."""
        cfg = self.REPORT_CONFIGS[report_type]

        if not period_end:
            period_end = datetime.now(timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        if not period_start:
            period_start = period_end - timedelta(days=cfg["days"])

        # 데이터 수집
        data = await self._collect_report_data(
            cluster_name, period_start, period_end, cfg["interval"]
        )

        # 예측 데이터 추가 (월간/연간)
        if report_type in ("monthly", "yearly") and self.predictor:
            data["predictions"] = await self.predictor.predict(cluster_name)

        report_id = f"{report_type}-{period_start.strftime('%Y%m%d')}-{cluster_name}"
        files = {}

        for fmt in output_formats:
            path = await self._write_report(report_id, fmt, data)
            files[fmt] = path

        # DB에 리포트 이력 기록
        await self.db.insert_report_record(
            report_type=report_type,
            cluster_name=cluster_name,
            period_start=period_start,
            period_end=period_end,
            files=files,
            summary=data["summary"],
        )

        return {"report_id": report_id, "files": files, "summary": data["summary"]}

    async def _collect_report_data(
        self, cluster_name, start, end, interval
    ) -> dict:
        nodes = await self.db.query_cluster_nodes(cluster_name)

        os_data = {}
        k8s_data = {}
        for node in nodes:
            node_name = node["node_name"]
            os_data[node_name] = {
                metric: await self.db.query_metric_timeseries(
                    cluster_name, node_name, metric,
                    start.isoformat(), end.isoformat(), interval
                )
                for metric in [
                    "cpu_usage_ratio", "memory_usage_ratio",
                    "disk_usage_ratio", "load1"
                ]
            }
            k8s_data[node_name] = {
                metric: await self.db.query_metric_timeseries(
                    cluster_name, node_name, metric,
                    start.isoformat(), end.isoformat(), interval,
                    table="k8s_metrics"
                )
                for metric in ["cpu_usage_ratio", "memory_usage_ratio"]
            }

        events = await self.db.query_events(
            cluster_name=cluster_name,
            start=start.isoformat(),
            end=end.isoformat()
        )

        summary = self._build_summary(nodes, os_data, k8s_data, events)

        return {
            "cluster_name": cluster_name,
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "interval": interval,
            "nodes": nodes,
            "os_metrics": os_data,
            "k8s_metrics": k8s_data,
            "events": events,
            "summary": summary,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _build_summary(self, nodes, os_data, k8s_data, events) -> dict:
        """리포트 요약 통계를 계산한다."""
        all_cpu = [
            v["avg"]
            for nd in os_data.values()
            for v in nd.get("cpu_usage_ratio", [])
        ]
        all_mem = [
            v["avg"]
            for nd in os_data.values()
            for v in nd.get("memory_usage_ratio", [])
        ]
        peak_cpu = max(
            (
                (nd_name, max((v["max"] for v in nd.get("cpu_usage_ratio", [])), default=0))
                for nd_name, nd in os_data.items()
            ),
            key=lambda x: x[1],
            default=("N/A", 0),
        )

        return {
            "nodes_total": len(nodes),
            "cpu_avg": round(sum(all_cpu) / len(all_cpu), 2) if all_cpu else 0,
            "memory_avg": round(sum(all_mem) / len(all_mem), 2) if all_mem else 0,
            "peak_cpu_node": peak_cpu[0],
            "peak_cpu_ratio": peak_cpu[1],
            "alerts_total": len(events),
            "alerts_critical": sum(1 for e in events if e["severity"] == "critical"),
        }

    async def _write_report(self, report_id: str, fmt: str, data: dict) -> str:
        """포맷에 맞게 파일로 저장한다."""
        output_dir = os.environ.get("REPORT_OUTPUT_DIR", "/reports")
        os.makedirs(output_dir, exist_ok=True)
        path = f"{output_dir}/{report_id}.{fmt}"

        if fmt == "json":
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

        elif fmt == "html":
            template = self.jinja_env.get_template("report.html.j2")
            html = template.render(**data)
            with open(path, "w", encoding="utf-8") as f:
                f.write(html)

        elif fmt == "pdf":
            # HTML → PDF 변환 (WeasyPrint)
            html_path = path.replace(".pdf", ".html")
            await self._write_report(report_id, "html", data)
            from weasyprint import HTML
            HTML(filename=html_path).write_pdf(path)

        return path
```

## Jinja2 HTML 템플릿 구조

```html
{# templates/report.html.j2 #}
<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <title>{{ cluster_name }} 모니터링 리포트 ({{ period_start[:10] }})</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
  <style>
    /* 리포트 스타일: 인쇄 최적화 */
    body { font-family: 'Noto Sans KR', sans-serif; margin: 20px; }
    .section { page-break-inside: avoid; margin: 30px 0; }
    .gauge { display: inline-block; width: 120px; text-align: center; }
    .ratio-bar { height: 20px; background: #eee; border-radius: 4px; }
    .ratio-fill { height: 100%; border-radius: 4px; }
    .ratio-ok   { background: #22c55e; }
    .ratio-warn { background: #f59e0b; }
    .ratio-crit { background: #ef4444; }
    table { width: 100%; border-collapse: collapse; }
    th, td { padding: 8px 12px; border: 1px solid #e5e7eb; text-align: right; }
    th { background: #f9fafb; text-align: left; }
  </style>
</head>
<body>
  <h1>{{ cluster_name }} 모니터링 리포트</h1>
  <p>기간: {{ period_start[:10] }} ~ {{ period_end[:10] }}</p>

  {# 요약 카드 #}
  <section class="section">
    <h2>요약</h2>
    <table>
      <tr><th>노드 수</th><td>{{ summary.nodes_total }}</td></tr>
      <tr><th>CPU 평균 사용률</th><td>{{ summary.cpu_avg }}%</td></tr>
      <tr><th>Memory 평균 사용률</th><td>{{ summary.memory_avg }}%</td></tr>
      <tr><th>최대 CPU 노드</th><td>{{ summary.peak_cpu_node }} ({{ summary.peak_cpu_ratio }}%)</td></tr>
      <tr><th>발생 경보</th><td>{{ summary.alerts_total }}건 (위험 {{ summary.alerts_critical }}건)</td></tr>
    </table>
  </section>

  {# OS 영역 — 노드별 #}
  <section class="section">
    <h2>OS 영역</h2>
    {% for node_name, metrics in os_metrics.items() %}
    <h3>{{ node_name }}</h3>
    <canvas id="cpu-{{ loop.index }}" height="80"></canvas>
    <script>
      new Chart(document.getElementById('cpu-{{ loop.index }}'), {
        type: 'line',
        data: {
          labels: {{ metrics.cpu_usage_ratio | map(attribute='time') | list | tojson }},
          datasets: [{
            label: 'CPU 사용률 (%)',
            data: {{ metrics.cpu_usage_ratio | map(attribute='avg') | list | tojson }},
            borderColor: '#3b82f6', fill: false,
          }]
        },
        options: { scales: { y: { min: 0, max: 100 } } }
      });
    </script>
    {% endfor %}
  </section>
</body>
</html>
```

## 의존성

```
jinja2>=3.1.0
weasyprint>=60.0   # PDF 변환 (선택)
```

## 참고

- 리포트 스케줄링: CronJob으로 매일 00:05 UTC에 자동 실행
- 대용량 리포트: 연간 리포트는 노드 수 * 쿼리가 많으므로 비동기 태스크로 처리
