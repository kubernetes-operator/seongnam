"""SSH를 통해 Prometheus에 없는 OS 보완 정보를 수집한다."""
import asyncio
import logging

logger = logging.getLogger(__name__)

try:
    import asyncssh
    HAS_ASYNCSSH = True
except ImportError:
    HAS_ASYNCSSH = False
    logger.warning("asyncssh 미설치 — SSH 보완 수집 비활성화")


async def supplement_node(node_ip: str, node_name: str) -> dict:
    """SSH로 Prometheus에 없는 정보를 수집한다. 실패 시 빈 dict 반환."""
    if not HAS_ASYNCSSH:
        return {}
    try:
        async with asyncssh.connect(
            node_ip,
            username="kwlee",
            known_hosts=None,
            connect_timeout=10,
        ) as conn:
            cpu_r    = await conn.run("nproc")
            zombie_r = await conn.run("ps aux | awk '$8==\"Z\"' | wc -l")
            inode_r  = await conn.run("df -i / --output=iuse% 2>/dev/null | tail -1 | tr -d '%'")
            uptime_r = await conn.run("cat /proc/uptime | awk '{print $1}'")

        return {
            "cpu_cores":         int(cpu_r.stdout.strip() or 1),
            "processes_zombie":  int(zombie_r.stdout.strip() or 0),
            "inode_usage_ratio": float(inode_r.stdout.strip() or 0),
            "uptime_sec":        float(uptime_r.stdout.strip() or 0),
        }
    except Exception as e:
        logger.warning("SSH 보완 실패 %s (%s): %s", node_name, node_ip, e)
        return {}


async def supplement_all(node_ip_map: dict[str, str]) -> dict[str, dict]:
    """모든 노드를 병렬로 SSH 보완 수집한다."""
    names = list(node_ip_map.keys())
    results = await asyncio.gather(
        *[supplement_node(node_ip_map[n], n) for n in names],
        return_exceptions=True,
    )
    return {
        name: (r if not isinstance(r, Exception) else {})
        for name, r in zip(names, results)
    }
