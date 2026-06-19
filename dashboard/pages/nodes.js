import { API } from '../api.js'
import { renderGauge } from '../components/gauge.js'

export async function renderNodes(cluster) {
  const main = document.getElementById('main-content')
  if (!cluster) { main.innerHTML = '<p class="text-muted">클러스터를 선택하세요.</p>'; return }

  main.innerHTML = `
    <h5 class="mb-3">노드 현황 — <span class="text-primary">${cluster}</span></h5>
    <div id="nodes-table"></div>
  `

  const [nodes, summary] = await Promise.all([
    API.nodes.list(cluster),
    API.metrics.summary(cluster),
  ]).catch(() => [{data:[]}, {data:{os:{}}}])

  // API returns arrays; convert to dicts keyed by node_name
  const osData  = Object.fromEntries((summary?.data?.os  || []).map(r => [r.node_name, r]))
  const k8sData = Object.fromEntries((summary?.data?.k8s || []).map(r => [r.node_name, r]))

  const rows = (nodes?.data || []).map(n => {
    const os  = osData[n.node_name]  || {}
    const k8s = k8sData[n.node_name] || {}
    const cpu  = os.cpu_usage_ratio    || 0
    const mem  = os.memory_usage_ratio || 0
    const disk = os.disk_usage_ratio   || 0
    const icon = (v, w=80, c=90) => v>=c ? '🔴' : v>=w ? '🟡' : '✅'
    return `<tr>
      <td>${n.node_name}</td>
      <td>${n.node_ip}</td>
      <td><span class="badge bg-secondary">${n.role||''}</span></td>
      <td class="${cpu>=90?'text-danger':cpu>=80?'text-warning':'text-success'}">${icon(cpu)} ${cpu.toFixed(1)}%</td>
      <td class="${mem>=90?'text-danger':mem>=80?'text-warning':'text-success'}">${icon(mem)} ${mem.toFixed(1)}%</td>
      <td class="${disk>=90?'text-danger':disk>=75?'text-warning':'text-success'}">${icon(disk,75,90)} ${disk.toFixed(1)}%</td>
      <td>${k8s.pods_running||0}</td>
      <td>${n.os_distro||''}</td>
    </tr>`
  }).join('')

  document.getElementById('nodes-table').innerHTML = `
    <div class="table-responsive">
      <table class="table table-sm table-hover">
        <thead class="table-light">
          <tr><th>노드</th><th>IP</th><th>역할</th><th>CPU</th><th>Memory</th><th>Disk</th><th>Pod수</th><th>OS</th></tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `
}
