import { API } from '../api.js'

export async function renderNodes(cluster) {
  const main = document.getElementById('main-content')
  if (!cluster) { main.innerHTML = '<p class="muted">클러스터를 선택하세요.</p>'; return }

  main.innerHTML = `
    <h2>노드 현황 — <span style="color:var(--info)">${cluster}</span></h2>
    <div id="nodes-table"></div>
  `

  const [nodes, summary] = await Promise.all([
    API.nodes.list(cluster),
    API.metrics.summary(cluster),
  ]).catch(() => [{data:[]}, {data:{os:{}}}])

  const osData = Object.fromEntries((summary?.data?.os || []).map(r => [r.node_name, r]))

  const cls = (v, w, c) => v >= c ? 'text-critical' : v >= w ? 'text-warning' : 'text-ok'
  const icon = (v, w=80, c=90) => v >= c ? '🔴' : v >= w ? '🟡' : '✅'

  const rows = (nodes?.data || []).map(n => {
    const os = osData[n.node_name] || {}
    const cpu  = os.cpu_usage_ratio    || 0
    const mem  = os.memory_usage_ratio || 0
    const disk = os.disk_usage_ratio   || 0
    return `<tr>
      <td>${n.node_name}</td>
      <td>${n.node_ip || ''}</td>
      <td class="${cls(cpu,80,90)}">${icon(cpu)} ${cpu.toFixed(1)}%</td>
      <td class="${cls(mem,80,90)}">${icon(mem)} ${mem.toFixed(1)}%</td>
      <td class="${cls(disk,75,90)}">${icon(disk,75,90)} ${disk.toFixed(1)}%</td>
      <td>${n.os_distro || ''}</td>
    </tr>`
  }).join('')

  document.getElementById('nodes-table').innerHTML = `
    <div class="table-wrap">
      <table class="findings-table">
        <thead><tr><th>노드</th><th>IP</th><th>CPU</th><th>Memory</th><th>Disk</th><th>OS</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="6" class="muted">노드 데이터가 없습니다.</td></tr>'}</tbody>
      </table>
    </div>
  `
}
