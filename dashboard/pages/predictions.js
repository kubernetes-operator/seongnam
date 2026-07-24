import { API } from '../api.js'

function _cls(v) { return v >= 90 ? 'text-critical' : v >= 80 ? 'text-warning' : 'text-ok' }

export async function renderPredictions(cluster) {
  const main = document.getElementById('main-content')
  if (!cluster) { main.innerHTML = '<p class="muted">클러스터를 선택하세요.</p>'; return }

  main.innerHTML = `
    <h2>예측 분석 — <span style="color:var(--info)">${cluster}</span></h2>
    <div id="pred-content"><div class="loading">불러오는 중…</div></div>
  `

  const result = await API.predictions.cluster(cluster).catch(() => null)
  const data  = result?.data || {}
  const nodes = data.nodes || []
  const recs  = data.recommendations || []

  const METRICS = [
    { key: 'cpu_usage_ratio',    label: 'CPU' },
    { key: 'memory_usage_ratio', label: 'Memory' },
    { key: 'disk_usage_ratio',   label: 'Disk' },
  ]

  const CONF = {
    high:     { label: '높음',  cls: 'text-ok' },
    medium:   { label: '보통',  cls: 'text-ok' },
    low:      { label: '낮음',  cls: 'text-warning' },
    very_low: { label: '매우낮음', cls: 'text-warning' },
  }

  const rows = nodes.map(n => METRICS.map(m => {
    const p = (n.predictions || {})[m.key]
    // 진짜 데이터가 하나도 없을 때만 '데이터 없음'
    if (!p || !p.status || p.status === 'insufficient_data') {
      return `<tr><td>${n.node_name}</td><td>${m.label}</td><td colspan="5" class="muted">데이터 없음 (수집 대기 중)</td></tr>`
    }
    const cur = p.current_value || 0, d7 = p.forecast_7d || 0, d30 = p.forecast_30d || 0
    const dtf = p.days_to_full
    const dtfs = dtf ? `${dtf.toFixed(0)}일` : '∞'
    const c = CONF[p.confidence] || CONF.low
    const conf = `<span class="${c.cls}">${c.label}</span>` +
      (p.reliable ? '' : ` <span class="muted" title="${p.message || ''}">(${p.data_points}일 추정)</span>`)
    return `<tr>
      <td>${n.node_name}</td>
      <td>${m.label}</td>
      <td class="${_cls(cur)}">${cur.toFixed(1)}%</td>
      <td class="${_cls(d7)}">${d7.toFixed(1)}%</td>
      <td class="${_cls(d30)}">${d30.toFixed(1)}%</td>
      <td class="${dtf && dtf < 30 ? 'text-critical fw-bold' : 'text-ok'}">${dtfs}</td>
      <td>${conf}</td>
    </tr>`
  }).join('')).flat().join('')

  const recHtml = recs.map(r => `
    <div class="alert ${r.urgency === 'HIGH' ? 'alert-danger' : 'alert-warning'}">
      <b>[${r.urgency}]</b> ${r.node_name} · ${r.metric} — ${r.message}
    </div>
  `).join('')

  document.getElementById('pred-content').innerHTML = `
    <div class="table-wrap mb-4">
      <table class="findings-table">
        <thead><tr><th>노드</th><th>메트릭</th><th>현재</th><th>7일후</th><th>30일후</th><th>포화까지</th><th>신뢰도</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="7" class="muted">예측 데이터가 없습니다.</td></tr>'}</tbody>
      </table>
    </div>
    ${recHtml ? `<h3>권장 조치</h3>${recHtml}` : '<p class="muted">권장 조치 없음</p>'}
  `
}
