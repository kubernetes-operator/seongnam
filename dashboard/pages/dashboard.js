import { API } from '../api.js'
import { renderGauge } from '../components/gauge.js'

function _fmtTime(t) {
  if (!t) return '-'
  const d = new Date(t)
  if (isNaN(d.getTime())) return String(t).slice(0, 16).replace('T', ' ')
  return d.toLocaleString('ko-KR', { hour12: false })
}

export async function renderDashboard(cluster) {
  const main = document.getElementById('main-content')
  if (!cluster) {
    main.innerHTML = '<p class="muted">클러스터를 선택하세요.</p>'
    return
  }

  main.innerHTML = `
    <h2>클러스터 요약 — <span style="color:var(--info)">${cluster}</span></h2>
    <div id="gauges" class="summary-gauges"></div>
    <div id="top-nodes" class="mb-4"></div>
    <div id="action-items"></div>
  `

  const [summary, top, events] = await Promise.all([
    API.metrics.summary(cluster),
    API.metrics.top(cluster, 'cpu_usage_ratio', 5),
    API.events.list(cluster, false, 50),
  ]).catch(() => [{}, [], { data: [] }])

  // 게이지 — 클러스터 평균
  const nodeList = summary?.data?.os || []
  if (nodeList.length) {
    const avg = (key) => nodeList.reduce((s, n) => s + (n[key] || 0), 0) / nodeList.length
    const metrics = ['cpu_usage_ratio', 'memory_usage_ratio', 'disk_usage_ratio']
    const labels  = ['CPU', 'Memory', 'Disk']
    document.getElementById('gauges').innerHTML = metrics.map((m, i) => `
      <div class="card text-center">
        <div class="card-title">${labels[i]} 평균</div>
        <canvas id="gauge-${m}" height="100"></canvas>
      </div>
    `).join('')
    metrics.forEach(m => renderGauge(`gauge-${m}`, avg(m), m))
  } else {
    document.getElementById('gauges').innerHTML = '<p class="muted">메트릭 데이터가 없습니다.</p>'
  }

  // CPU 상위 노드
  const topData = top?.data || []
  document.getElementById('top-nodes').innerHTML = `
    <div class="card">
      <div class="card-title">CPU 상위 5개 노드</div>
      ${topData.map((n, i) => `
        <div style="display:flex;justify-content:space-between;font-size:13px;margin:4px 0">
          <span>${i + 1}. ${n.node_name}</span>
          <span class="${n.avg_value >= 90 ? 'text-critical' : n.avg_value >= 80 ? 'text-warning' : 'text-ok'}">${n.avg_value?.toFixed(1)}%</span>
        </div>
      `).join('') || '<span class="muted">데이터 없음</span>'}
    </div>
  `

  // 조치 필요 항목 (성능 하단, 최대 10개)
  renderActionItems(events, top)
}

// 조치 필요 항목 패널 — 클릭 시 해당 메뉴로 이동
function renderActionItems(events, top) {
  const el = document.getElementById('action-items')
  if (!el) return

  const evtList   = (events?.data || []).filter(ev => !ev.resolved_at)
  const critNodes = (top?.data || []).filter(n => n.avg_value >= 80)
  const items = []

  evtList.forEach(ev => {
    const d = typeof ev.details === 'string' ? JSON.parse(ev.details || '{}') : (ev.details || {})
    const sev = ev.severity || 'warning'
    items.push({
      icon: sev === 'critical' ? '🔴' : '🟠',
      sevClass: sev === 'critical' ? 'sev-critical' : 'sev-warning',
      label: sev,
      title: `${d.crisis_type || ev.event_type || '위기 이벤트'} — ${ev.node_name || ''}`,
      time: _fmtTime(ev.time || ev.created_at),
      onclick: `window.goToEvent(${ev.id})`,
    })
  })

  critNodes.forEach(n => {
    const crit = n.avg_value >= 90
    items.push({
      icon: crit ? '🔴' : '🟠',
      sevClass: crit ? 'sev-critical' : 'sev-warning',
      label: crit ? 'critical' : 'warning',
      title: `${n.node_name} CPU ${n.avg_value?.toFixed(1)}%`,
      time: '리소스 임계값 초과',
      onclick: `window.goToNodes()`,
    })
  })

  if (!items.length) {
    el.innerHTML = `<div class="card"><span class="text-ok">✅ 조치가 필요한 항목이 없습니다.</span></div>`
    return
  }

  const LIMIT = 10
  const shown = items.slice(0, LIMIT)
  const overflow = items.length - shown.length

  el.innerHTML = `
    <div class="card card-flush">
      <div class="card-header">
        <span>⚠️ 조치 필요 항목</span>
        <span class="badge badge-count">${items.length}</span>
      </div>
      <div class="list-flush">
        ${shown.map(it => `
          <button type="button" class="list-item" onclick="${it.onclick}">
            <span>
              <span style="margin-right:6px">${it.icon}</span>
              <span class="sev-pill ${it.sevClass}" style="margin-right:8px">${it.label}</span>
              ${it.title}
            </span>
            <span class="muted">${it.time} ›</span>
          </button>
        `).join('')}
      </div>
      ${overflow > 0 ? `<button type="button" class="card-link" onclick="window.goToEvents()">외 ${overflow}건 더 보기 →</button>` : ''}
    </div>
  `
}

// 이벤트 항목 클릭 → 이벤트 메뉴로 이동하며 해당 이벤트 상세를 자동으로 연다
window.goToEvent = (id) => {
  window.__openEventId = id
  location.hash = '#events'
}
// 노드 항목 클릭 → 노드 메뉴로 이동
window.goToNodes = () => { location.hash = '#nodes' }
// '더 보기' → 이벤트 목록 메뉴로 이동
window.goToEvents = () => { location.hash = '#events' }
