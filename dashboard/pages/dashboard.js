import { API } from '../api.js'
import { renderGauge } from '../components/gauge.js'

export async function renderDashboard(cluster) {
  const main = document.getElementById('main-content')
  if (!cluster) {
    main.innerHTML = '<p class="text-muted">클러스터를 선택하세요.</p>'
    return
  }

  main.innerHTML = `
    <h5 class="mb-3">클러스터 요약 — <span class="text-primary">${cluster}</span></h5>
    <div id="gauges" class="row g-3 mb-4"></div>
    <div class="row g-3">
      <div class="col-md-8"><canvas id="trend-chart" height="120"></canvas></div>
      <div class="col-md-4" id="top-nodes"></div>
    </div>
  `

  const [summary, top] = await Promise.all([
    API.metrics.summary(cluster),
    API.metrics.top(cluster, 'cpu_usage_ratio', 5),
  ]).catch(() => [{}, []])

  // Gauges — 클러스터 평균
  const nodeList = Object.values(summary?.data?.os || {})
  if (nodeList.length) {
    const avg = (key) => nodeList.reduce((s, n) => s + (n[key] || 0), 0) / nodeList.length
    const gaugesEl = document.getElementById('gauges')
    gaugesEl.innerHTML = ['cpu_usage_ratio','memory_usage_ratio','disk_usage_ratio'].map((m,i) => `
      <div class="col-md-4">
        <div class="card p-3 text-center">
          <div class="card-title small text-muted">${['CPU','Memory','Disk'][i]} 평균</div>
          <canvas id="gauge-${m}" height="100"></canvas>
        </div>
      </div>
    `).join('')
    ;['cpu_usage_ratio','memory_usage_ratio','disk_usage_ratio'].forEach(m =>
      renderGauge(`gauge-${m}`, avg(m), m)
    )
  }

  // Top nodes
  const topData = top?.data || []
  document.getElementById('top-nodes').innerHTML = `
    <div class="card p-3">
      <div class="card-title small text-muted">CPU 상위 5개 노드</div>
      ${topData.map((n,i) => `
        <div class="d-flex justify-content-between small mb-1">
          <span>${i+1}. ${n.node_name}</span>
          <span class="${n.value>=90?'text-danger':n.value>=80?'text-warning':'text-success'}">${n.value?.toFixed(1)}%</span>
        </div>
      `).join('')}
    </div>
  `
}
