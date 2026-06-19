import { API } from '../api.js'

function _color(v) { return v>=90?'danger':v>=80?'warning':'success' }

export async function renderPredictions(cluster) {
  const main = document.getElementById('main-content')
  if (!cluster) { main.innerHTML = '<p class="text-muted">클러스터를 선택하세요.</p>'; return }

  main.innerHTML = `
    <h5 class="mb-3">예측 분석 — <span class="text-primary">${cluster}</span></h5>
    <div id="pred-content"><div class="spinner-border text-primary" role="status"></div></div>
  `

  const result = await API.predictions.cluster(cluster).catch(() => null)
  const data   = result?.data || {}
  const nodes  = data.nodes || []
  const recs   = data.recommendations || []

  const METRICS = [
    { key: 'cpu_usage_ratio',    label: 'CPU' },
    { key: 'memory_usage_ratio', label: 'Memory' },
    { key: 'disk_usage_ratio',   label: 'Disk' },
  ]

  const rows = nodes.map(n => METRICS.map(m => {
    const p = (n.predictions||{})[m.key]
    // 데이터 없음 또는 부족 상태
    if (!p || !p.status || p.status === 'insufficient_data') {
      return `<tr><td>${n.node_name}</td><td>${m.label}</td><td colspan="4" class="text-muted small">데이터 부족 (수집 14일 후 표시)</td></tr>`
    }
    const cur  = p.current_value||0
    const d7   = p.forecast_7d||0
    const d30  = p.forecast_30d||0
    const dtf  = p.days_to_full
    const dtfs = dtf ? `${dtf.toFixed(0)}일` : '∞'
    return `<tr>
      <td>${n.node_name}</td>
      <td>${m.label}</td>
      <td class="text-${_color(cur)}">${cur.toFixed(1)}%</td>
      <td class="text-${_color(d7)}">${d7.toFixed(1)}%</td>
      <td class="text-${_color(d30)}">${d30.toFixed(1)}%</td>
      <td class="${dtf&&dtf<30?'text-danger fw-bold':'text-success'}">${dtfs}</td>
    </tr>`
  }).join('')).flat().join('')

  const recHtml = recs.map(r => `
    <div class="alert alert-${r.urgency==='HIGH'?'danger':'warning'} py-2">
      <b>[${r.urgency}]</b> ${r.node_name} · ${r.metric} — ${r.message}
    </div>
  `).join('')

  document.getElementById('pred-content').innerHTML = `
    <div class="table-responsive mb-4">
      <table class="table table-sm table-hover">
        <thead class="table-light">
          <tr><th>노드</th><th>메트릭</th><th>현재</th><th>7일후</th><th>30일후</th><th>포화까지</th></tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
    ${recHtml ? `<h6>권장 조치</h6>${recHtml}` : '<p class="text-muted small">권장 조치 없음</p>'}
  `
}
