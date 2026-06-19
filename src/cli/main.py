"""K8s OS Monitor CLI — Typer + Rich."""
import asyncio
import json
import os
from datetime import datetime, timezone, timedelta
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich import box
from rich.text import Text

app = typer.Typer(name="monitor", help="K8s OS Monitor CLI")
console = Console()

# ── 임계값 색상 ─────────────────────────────────────────────────────────────

def _color(value: float, warn: float = 80.0, crit: float = 90.0) -> str:
    if value >= crit:
        return "red"
    if value >= warn:
        return "yellow"
    return "green"


def _icon(value: float, warn: float = 80.0, crit: float = 90.0) -> str:
    if value >= crit:
        return "🔴"
    if value >= warn:
        return "🟡"
    return "✅"


def _pct(v) -> str:
    if v is None:
        return "N/A"
    return f"{float(v):.1f}%"


# ── DB 연결 헬퍼 ─────────────────────────────────────────────────────────────

def _get_pool():
    from db.pool import get_pool as _pool
    return asyncio.get_event_loop().run_until_complete(_pool())


# ── status ──────────────────────────────────────────────────────────────────

@app.command()
def status(cluster: str = typer.Argument(..., help="클러스터 이름")):
    """클러스터 전체 상태 요약을 출력합니다."""
    async def _run():
        from db.pool import get_pool
        from db.queries import query_latest_metrics, query_latest_k8s_metrics, query_events
        pool = await get_pool()
        os_m  = await query_latest_metrics(pool, cluster)
        k8s_m = await query_latest_k8s_metrics(pool, cluster)
        evts  = await query_events(pool, cluster, resolved=False, limit=5)
        return os_m, k8s_m, evts

    os_m, k8s_m, evts = asyncio.run(_run())

    console.print(f"\n[bold cyan]클러스터:[/] {cluster}", highlight=False)

    # OS 요약
    t = Table(title="OS 현황", box=box.SIMPLE, show_lines=False)
    t.add_column("노드",       style="cyan",  no_wrap=True)
    t.add_column("CPU",        justify="right")
    t.add_column("Memory",     justify="right")
    t.add_column("Disk",       justify="right")
    t.add_column("Load/Core",  justify="right")
    for node, d in (os_m or {}).items():
        cpu  = d.get("cpu_usage_ratio",    0.0)
        mem  = d.get("memory_usage_ratio", 0.0)
        disk = d.get("disk_usage_ratio",   0.0)
        load = d.get("load_per_core",      0.0)
        t.add_row(
            node,
            Text(f"{_icon(cpu)} {_pct(cpu)}",   style=_color(cpu)),
            Text(f"{_icon(mem)} {_pct(mem)}",   style=_color(mem)),
            Text(f"{_icon(disk)} {_pct(disk)}", style=_color(disk, 75, 90)),
            Text(f"{_icon(load, 1.5, 2.0)} {load:.2f}", style=_color(load, 1.5, 2.0)),
        )
    console.print(t)

    # 미해결 이벤트
    if evts:
        e = Table(title="미해결 이벤트 (최근 5건)", box=box.SIMPLE)
        e.add_column("ID",     style="dim")
        e.add_column("심각도", style="bold")
        e.add_column("유형")
        e.add_column("노드")
        e.add_column("시각")
        for ev in evts:
            d = ev.get("details") or {}
            if isinstance(d, str):
                d = json.loads(d)
            sev = ev.get("severity", "")
            sev_color = "red" if sev == "critical" else "yellow"
            e.add_row(
                str(ev.get("id")),
                Text(sev, style=sev_color),
                d.get("crisis_type", ev.get("event_type", "")),
                ev.get("node_name", ""),
                str(ev.get("created_at", ""))[:16],
            )
        console.print(e)


# ── nodes ────────────────────────────────────────────────────────────────────

@app.command()
def nodes(cluster: str = typer.Argument(..., help="클러스터 이름")):
    """클러스터 노드 목록과 상태를 출력합니다."""
    async def _run():
        from db.pool import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM cluster_nodes WHERE cluster_name=$1 ORDER BY node_name",
                cluster,
            )
        return [dict(r) for r in rows]

    rows = asyncio.run(_run())
    t = Table(title=f"노드 목록 — {cluster}", box=box.ROUNDED)
    t.add_column("노드명",     style="cyan")
    t.add_column("IP")
    t.add_column("역할")
    t.add_column("OS")
    t.add_column("Kernel")
    t.add_column("CPU 코어", justify="right")
    t.add_column("Memory(GB)", justify="right")
    for r in rows:
        t.add_row(
            r.get("node_name", ""),
            r.get("node_ip", ""),
            r.get("role", ""),
            r.get("os_version", ""),
            r.get("kernel_version", ""),
            str(r.get("cpu_cores", "")),
            f"{(r.get('total_memory_bytes') or 0) / 1024**3:.1f}",
        )
    console.print(t)


# ── os ───────────────────────────────────────────────────────────────────────

@app.command()
def os_metrics(
    cluster: str = typer.Argument(..., help="클러스터 이름"),
    node: Optional[str] = typer.Option(None, help="특정 노드 (미입력 시 전체)"),
    hours: int = typer.Option(1, help="최근 N시간"),
):
    """OS 메트릭 상세 현황을 출력합니다."""
    async def _run():
        from db.pool import get_pool
        from db.queries import query_latest_metrics
        pool = await get_pool()
        return await query_latest_metrics(pool, cluster)

    data = asyncio.run(_run())
    t = Table(title=f"OS 메트릭 — {cluster}", box=box.ROUNDED)
    t.add_column("노드",         style="cyan", no_wrap=True)
    t.add_column("CPU%",         justify="right")
    t.add_column("Mem%",         justify="right")
    t.add_column("Disk%",        justify="right")
    t.add_column("Load/Core",    justify="right")
    t.add_column("Net↑(Mb/s)",   justify="right")
    t.add_column("Net↓(Mb/s)",   justify="right")
    t.add_column("Zombie",       justify="right")
    t.add_column("Inode%",       justify="right")
    for nname, d in (data or {}).items():
        if node and nname != node:
            continue
        cpu   = d.get("cpu_usage_ratio", 0.0)
        mem   = d.get("memory_usage_ratio", 0.0)
        disk  = d.get("disk_usage_ratio", 0.0)
        load  = d.get("load_per_core", 0.0)
        tx    = (d.get("network_tx_bytes", 0) or 0) / 125000
        rx    = (d.get("network_rx_bytes", 0) or 0) / 125000
        zomb  = d.get("processes_zombie", 0)
        inode = d.get("inode_usage_ratio", 0.0)
        t.add_row(
            nname,
            Text(f"{_icon(cpu)} {_pct(cpu)}",   style=_color(cpu)),
            Text(f"{_icon(mem)} {_pct(mem)}",   style=_color(mem)),
            Text(f"{_icon(disk)} {_pct(disk)}", style=_color(disk, 75, 90)),
            Text(f"{_icon(load,1.5,2.0)} {load:.2f}", style=_color(load,1.5,2.0)),
            f"{tx:.1f}",
            f"{rx:.1f}",
            str(zomb),
            _pct(inode),
        )
    console.print(t)


# ── k8s ─────────────────────────────────────────────────────────────────────

@app.command()
def k8s(
    cluster: str = typer.Argument(..., help="클러스터 이름"),
    node: Optional[str] = typer.Option(None, help="특정 노드"),
):
    """K8s 노드 메트릭을 출력합니다."""
    async def _run():
        from db.pool import get_pool
        from db.queries import query_latest_k8s_metrics
        pool = await get_pool()
        return await query_latest_k8s_metrics(pool, cluster)

    data = asyncio.run(_run())
    t = Table(title=f"K8s 메트릭 — {cluster}", box=box.ROUNDED)
    t.add_column("노드",         style="cyan", no_wrap=True)
    t.add_column("CPU요청%",     justify="right")
    t.add_column("CPU한도%",     justify="right")
    t.add_column("Mem요청%",     justify="right")
    t.add_column("Mem한도%",     justify="right")
    t.add_column("Pod수",        justify="right")
    t.add_column("상태",         justify="center")
    for nname, d in (data or {}).items():
        if node and nname != node:
            continue
        cpu_req = d.get("cpu_request_ratio", 0.0)
        cpu_lim = d.get("cpu_limit_ratio", 0.0)
        mem_req = d.get("memory_request_ratio", 0.0)
        mem_lim = d.get("memory_limit_ratio", 0.0)
        pods    = d.get("pod_count", 0)
        ready   = d.get("ready", True)
        status_icon = "✅ Ready" if ready else "🔴 NotReady"
        t.add_row(
            nname,
            Text(f"{_icon(cpu_req)} {_pct(cpu_req)}", style=_color(cpu_req)),
            Text(_pct(cpu_lim), style=_color(cpu_lim)),
            Text(f"{_icon(mem_req)} {_pct(mem_req)}", style=_color(mem_req)),
            Text(_pct(mem_lim), style=_color(mem_lim)),
            str(pods),
            Text(status_icon, style="green" if ready else "red"),
        )
    console.print(t)


# ── top ──────────────────────────────────────────────────────────────────────

@app.command()
def top(
    cluster: str = typer.Argument(..., help="클러스터 이름"),
    metric: str = typer.Option("cpu_usage_ratio", help="메트릭 이름"),
    limit: int = typer.Option(5, help="상위 N개"),
):
    """상위 N개 노드를 출력합니다."""
    async def _run():
        from db.pool import get_pool
        from db.queries import query_top_nodes
        pool = await get_pool()
        return await query_top_nodes(pool, cluster, metric, limit)

    rows = asyncio.run(_run())
    t = Table(title=f"TOP {limit} — {metric}", box=box.SIMPLE)
    t.add_column("순위", justify="right", style="dim")
    t.add_column("노드", style="cyan")
    t.add_column("값",   justify="right")
    for i, r in enumerate(rows or [], 1):
        val = r.get("value", 0.0)
        t.add_row(str(i), r.get("node_name", ""), Text(_pct(val), style=_color(val)))
    console.print(t)


# ── events ───────────────────────────────────────────────────────────────────

@app.command()
def events(
    cluster: str = typer.Argument(..., help="클러스터 이름"),
    resolved: bool = typer.Option(False, help="해결된 이벤트 포함"),
    limit: int = typer.Option(20),
):
    """위기 이벤트 목록을 출력합니다."""
    async def _run():
        from db.pool import get_pool
        from db.queries import query_events
        pool = await get_pool()
        return await query_events(pool, cluster, resolved=resolved, limit=limit)

    evts = asyncio.run(_run())
    t = Table(title=f"이벤트 — {cluster}", box=box.ROUNDED)
    t.add_column("ID",     style="dim")
    t.add_column("심각도", style="bold")
    t.add_column("유형")
    t.add_column("노드",   style="cyan")
    t.add_column("시각")
    t.add_column("해결")
    for ev in (evts or []):
        d = ev.get("details") or {}
        if isinstance(d, str):
            d = json.loads(d)
        sev = ev.get("severity", "")
        t.add_row(
            str(ev.get("id")),
            Text(sev, style="red" if sev == "critical" else "yellow"),
            d.get("crisis_type", ev.get("event_type", "")),
            ev.get("node_name", ""),
            str(ev.get("created_at", ""))[:16],
            "✅" if ev.get("resolved_at") else "⏳",
        )
    console.print(t)


# ── predict ──────────────────────────────────────────────────────────────────

@app.command()
def predict(
    cluster: str = typer.Argument(..., help="클러스터 이름"),
    node: Optional[str] = typer.Option(None, help="특정 노드"),
):
    """미래 상태 예측 결과를 출력합니다."""
    async def _run():
        from db.pool import get_pool
        from db.queries import query_metric_timeseries
        from analysis.predictor import TrendPredictor
        pool = await get_pool()
        predictor = TrendPredictor()
        end   = datetime.now(timezone.utc).isoformat()
        start = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

        # 노드 목록
        async with pool.acquire() as conn:
            node_names = [r["node_name"] for r in await conn.fetch(
                "SELECT node_name FROM cluster_nodes WHERE cluster_name=$1", cluster
            )]
        if node:
            node_names = [n for n in node_names if n == node]

        results = {}
        for nname in node_names:
            preds = {}
            for m in ["cpu_usage_ratio", "memory_usage_ratio", "disk_usage_ratio"]:
                ts = await query_metric_timeseries(pool, cluster, nname, m, start, end, "1d")
                preds[m] = predictor.predict_metric(ts, metric_name=m)
            results[nname] = preds
        return results

    results = asyncio.run(_run())
    t = Table(title=f"예측 — {cluster}", box=box.ROUNDED)
    t.add_column("노드",    style="cyan", no_wrap=True)
    t.add_column("메트릭")
    t.add_column("현재%",   justify="right")
    t.add_column("7일후",   justify="right")
    t.add_column("30일후",  justify="right")
    t.add_column("포화까지", justify="right")
    for nname, preds in results.items():
        for m, p in preds.items():
            if p.get("status") == "insufficient_data":
                t.add_row(nname, m, "N/A", "N/A", "N/A", "데이터부족")
                continue
            cur  = p.get("current_value", 0.0)
            d7   = p.get("forecast_7d", 0.0)
            d30  = p.get("forecast_30d", 0.0)
            dtf  = p.get("days_to_full")
            dtf_s = f"{dtf:.0f}일" if dtf else "∞"
            t.add_row(
                nname, m,
                Text(_pct(cur),  style=_color(cur)),
                Text(_pct(d7),   style=_color(d7)),
                Text(_pct(d30),  style=_color(d30)),
                Text(dtf_s, style="red" if dtf and dtf < 30 else "green"),
            )
    console.print(t)


# ── report ───────────────────────────────────────────────────────────────────

@app.command()
def report(
    cluster: str = typer.Argument(..., help="클러스터 이름"),
    report_type: str = typer.Option("daily", help="daily/weekly/monthly/yearly"),
    output: str = typer.Option("both", help="html/json/both"),
):
    """리포트를 생성합니다."""
    async def _run():
        from db.pool import get_pool
        from reports.generator import ReportGenerator
        pool = await get_pool()
        gen = ReportGenerator(pool)
        formats = ["html", "json"] if output == "both" else [output]
        return await gen.generate(report_type, cluster, formats)

    console.print(f"[cyan]리포트 생성 중...[/] {cluster} / {report_type}")
    result = asyncio.run(_run())
    if result:
        console.print(f"[green]완료:[/] {result}")
    else:
        console.print("[red]리포트 생성 실패[/]")


if __name__ == "__main__":
    app()
