---
name: cli-table
description: |
  Rich 라이브러리를 사용하여 Kubernetes OS 모니터링 데이터를 CLI 터미널 표(Table) 형태로 출력하는 Python 코드를 구현한다. 색상 기반 상태 표시, 최대 대비 비율 강조, 자동 갱신, API 연동을 포함한다. 'CLI', '터미널 출력', 'Rich 테이블', '표 형태', 'k8s-monitor CLI', 'kubectl 대시보드' 관련 구현 시 반드시 이 스킬을 사용할 것.
---

# CLI Table 스킬

## CLI 도구 구조

```python
# cli/main.py
import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.live import Live
from rich.progress import Progress
import httpx, time

app = typer.Typer(help="K8s OS 모니터링 CLI 도구")
console = Console()

# API 클라이언트 설정
def get_api_client() -> httpx.Client:
    import yaml, os
    config_path = os.path.expanduser("~/.k8s-monitor/config.yaml")
    if os.path.exists(config_path):
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
    else:
        cfg = {}
    api_url = cfg.get("api_url", os.environ.get("K8S_MONITOR_URL", "http://localhost:8000"))
    api_key = cfg.get("api_key", os.environ.get("K8S_MONITOR_API_KEY", ""))
    return httpx.Client(
        base_url=api_url,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=15,
    )
```

## 상태 표시 헬퍼

```python
def ratio_to_color(ratio: float | None) -> str:
    """사용률에 따라 색상을 반환한다."""
    if ratio is None:
        return "white"
    if ratio >= 90:
        return "red"
    if ratio >= 75:
        return "yellow"
    return "green"

def ratio_display(ratio: float | None, width: int = 6) -> str:
    """사용률 값을 색상 포함 문자열로 포맷한다."""
    if ratio is None:
        return "[dim]N/A[/dim]"
    color = ratio_to_color(ratio)
    icon = "🔴" if ratio >= 90 else ("🟡" if ratio >= 75 else "✅")
    return f"[{color}]{ratio:5.1f}%[/{color}] {icon}"

def bytes_to_human(b: int | None) -> str:
    """바이트를 사람이 읽기 쉬운 단위로 변환한다."""
    if b is None:
        return "N/A"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(b) < 1024:
            return f"{b:.1f}{unit}"
        b /= 1024
    return f"{b:.1f}PB"
```

## 주요 명령 구현

### status 명령 — 전체 클러스터 현황

```python
@app.command()
def status(
    cluster: str = typer.Option(None, "--cluster", "-c", help="클러스터 이름"),
    watch: bool = typer.Option(False, "--watch", "-w", help="30초 자동 갱신"),
):
    """전체 클러스터 현황을 표로 출력한다."""
    def render():
        with get_api_client() as client:
            resp = client.get("/api/v1/clusters")
            resp.raise_for_status()
            clusters = resp.json()["data"]

        table = Table(
            title="K8s OS Monitor — 클러스터 현황",
            show_header=True,
            header_style="bold cyan",
            border_style="blue",
        )
        table.add_column("클러스터", style="bold", min_width=20)
        table.add_column("노드 (정상/전체)", justify="center")
        table.add_column("CPU 평균", justify="right")
        table.add_column("CPU 최대", justify="right")
        table.add_column("MEM 평균", justify="right")
        table.add_column("MEM 최대", justify="right")
        table.add_column("DISK 평균", justify="right")
        table.add_column("경보", justify="center")

        for cl in clusters:
            if cluster and cl["name"] != cluster:
                continue
            nodes_str = f"{cl.get('nodes_ready', 0)}/{cl.get('nodes_total', 0)}"
            alert_count = cl.get("alerts_count", 0)
            alert_str = f"[red]⚠️  {alert_count}[/red]" if alert_count > 0 else "[green]✅ 0[/green]"

            table.add_row(
                cl["name"],
                nodes_str,
                ratio_display(cl.get("cpu_avg")),
                ratio_display(cl.get("cpu_max")),
                ratio_display(cl.get("mem_avg")),
                ratio_display(cl.get("mem_max")),
                ratio_display(cl.get("disk_avg")),
                alert_str,
            )

        return table

    if watch:
        with Live(render(), refresh_per_second=0.5, console=console) as live:
            while True:
                time.sleep(30)
                live.update(render())
    else:
        console.print(render())
```

### nodes 명령 — 노드별 OS/K8s 메트릭

```python
@app.command()
def nodes(
    cluster: str = typer.Option(..., "--cluster", "-c"),
    area: str = typer.Option("os", "--area", "-a", help="os | k8s | all"),
    sort: str = typer.Option("cpu", "--sort", "-s", help="cpu | memory | disk | load"),
):
    """노드별 상세 메트릭을 표로 출력한다."""
    with get_api_client() as client:
        resp = client.get(f"/api/v1/metrics/summary/{cluster}")
        resp.raise_for_status()
        data = resp.json()["data"]

    # 정렬
    sort_keys = {
        "cpu": "cpu_avg", "memory": "mem_avg",
        "disk": "disk_avg", "load": "load_avg"
    }
    data.sort(key=lambda r: r.get(sort_keys.get(sort, "cpu_avg"), 0), reverse=True)

    if area in ("os", "all"):
        table = Table(
            title=f"[bold]🖥️  OS 영역[/bold] · {cluster}",
            header_style="bold cyan",
            border_style="blue",
        )
        table.add_column("노드", style="bold", min_width=12)
        table.add_column("CPU 평균", justify="right")
        table.add_column("CPU 최대", justify="right")
        table.add_column("MEM 평균", justify="right")
        table.add_column("MEM 최대", justify="right")
        table.add_column("DISK 평균", justify="right")
        table.add_column("Load Avg (1m)", justify="right")

        for row in data:
            table.add_row(
                row["node_name"],
                ratio_display(row.get("cpu_avg")),
                ratio_display(row.get("cpu_max")),
                ratio_display(row.get("mem_avg")),
                ratio_display(row.get("mem_max")),
                ratio_display(row.get("disk_avg")),
                f"{row.get('load_avg', 0):.2f}" if row.get("load_avg") else "N/A",
            )
        console.print(table)

    console.print(f"\n[dim]범례: ✅ 정상 (<75%)  🟡 경고 (75~90%)  🔴 위험 (>90%)[/dim]")
    console.print(f"[dim]정렬 기준: {sort} | 갱신: k8s-monitor nodes --cluster {cluster} --watch[/dim]")
```

### events 명령 — 위기 이벤트 목록

```python
@app.command()
def events(
    cluster: str = typer.Option(None, "--cluster"),
    severity: str = typer.Option(None, "--severity", help="warning | critical"),
    unresolved: bool = typer.Option(True, "--unresolved/--all"),
    limit: int = typer.Option(20, "--limit"),
):
    """위기 이벤트 목록을 표로 출력한다."""
    params = {"limit": limit}
    if cluster:
        params["cluster_name"] = cluster
    if severity:
        params["severity"] = severity
    if unresolved:
        params["resolved"] = "false"

    with get_api_client() as client:
        resp = client.get("/api/v1/events", params=params)
        resp.raise_for_status()
        data = resp.json()["data"]

    table = Table(
        title=f"🚨 위기 이벤트 ({len(data)}건)",
        header_style="bold red",
        border_style="red",
    )
    table.add_column("시각 (UTC)", min_width=16)
    table.add_column("심각도", justify="center")
    table.add_column("클러스터/노드", min_width=20)
    table.add_column("유형", min_width=20)
    table.add_column("요약", min_width=30)

    severity_icons = {"critical": "🔴 위험", "warning": "🟡 경고", "info": "🔵 정보"}

    for ev in data:
        sev = ev.get("severity", "")
        table.add_row(
            ev.get("time", "")[:16].replace("T", " "),
            severity_icons.get(sev, sev),
            f"{ev.get('cluster_name', '')}\n{ev.get('node_name', '')}",
            ev.get("event_type", ""),
            ev.get("message", "")[:50],
        )

    console.print(table)
    console.print("[dim]상세: k8s-monitor events --id <event_id>[/dim]")
```

### predict 명령 — 예측 결과

```python
@app.command()
def predict(
    cluster: str = typer.Option(..., "--cluster"),
    horizon: int = typer.Option(30, "--horizon", help="예측 기간 (일)"),
):
    """리소스 예측 결과를 표로 출력한다."""
    with get_api_client() as client:
        resp = client.get(f"/api/v1/predictions/{cluster}", params={"horizon": horizon})
        resp.raise_for_status()
        data = resp.json()["data"]

    table = Table(
        title=f"🔮 리소스 예측 · {cluster} ({horizon}일 기준)",
        header_style="bold magenta",
        border_style="magenta",
    )
    table.add_column("노드", min_width=12)
    table.add_column("메트릭")
    table.add_column("현재", justify="right")
    table.add_column("7일 후", justify="right")
    table.add_column("30일 후", justify="right")
    table.add_column("고갈 예상", justify="center")
    table.add_column("권고")

    for pred in data.get("predictions", []):
        days_to_full = pred.get("days_to_full")
        full_str = (
            f"[red]{pred.get('predicted_full_date', '')}[/red]"
            if days_to_full and days_to_full < 90
            else "[green]90일 이후[/green]"
        )
        table.add_row(
            pred.get("node_name", ""),
            pred.get("metric", ""),
            ratio_display(pred.get("current_value")),
            ratio_display(pred.get("predictions", {}).get("7d")),
            ratio_display(pred.get("predictions", {}).get("30d")),
            full_str,
            pred.get("trend_rate_label", ""),
        )

    console.print(table)

    recs = data.get("recommendations", [])
    if recs:
        console.print(Panel(
            "\n".join(f"[bold]{r['urgency'].upper()}[/bold]: {r['recommendation']}" for r in recs[:5]),
            title="권고 사항",
            border_style="yellow"
        ))

if __name__ == "__main__":
    app()
```

## 의존성

```
typer>=0.9.0
rich>=13.7.0
httpx>=0.25.0
pyyaml>=6.0
```

## 설치

```bash
pip install k8s-monitor-cli
# 또는
pip install -e .
```
