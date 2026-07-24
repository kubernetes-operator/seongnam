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
    <div class="row g-3 mb-4">
      <div class="col-md-8"><canvas id="trend-chart" height="120"></canvas></div>
      <div class="col-md-4" id="top-nodes"></div>
    </div>
    <div id="action-items"></div>
  `

  const [summary, top, events] = await Promise.all([
    API.metrics.summary(cluster),
    API.metrics.top(cluster, 'cpu_usage_ratio', 5),
    API.events.list(cluster, false, 50),
  ]).catch(() => [{}, [], { data: [] }])

  // 조치 필요 항목 — 미해결 위기 이벤트 + 임계값 초과 노드
  renderActionItems(events, top)

  // Gauges — 클러스터 평균 (API는 배열로 반환)
  const nodeList = summary?.data?.os || []
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
          <span class="${n.avg_value>=90?'text-danger':n.avg_value>=80?'text-warning':'text-success'}">${n.avg_value?.toFixed(1)}%</span>
        </div>
      `).join('')}
    </div>
  `
}

// 조치 필요 항목 패널 — 클릭 시 해당 메뉴로 이동
function renderActionItems(events, top) {
  const el = document.getElementById('action-items')
  if (!el) return

  const evtList = (events?.data || []).filter(ev => !ev.resolved_at)
  const critNodes = (top?.data || []).filter(n => n.avg_value >= 80)

  const items = []

  // 1) 미해결 위기 이벤트 → 이벤트 메뉴로 이동 후 상세 열기
  evtList.forEach(ev => {
    const d = typeof ev.details === 'string' ? JSON.parse(ev.details || '{}') : (ev.details || {})
    const sev = ev.severity || 'warning'
    items.push({
      icon: sev === 'critical' ? '🔴' : '🟠',
      sevClass: sev === 'critical' ? 'danger' : 'warning',
      label: sev,
      title: `${d.crisis_type || ev.event_type || '위기 이벤트'} — ${ev.node_name || ''}`,
      time: String(ev.created_at || '').slice(0, 16),
      onclick: `window.goToEvent(${ev.id})`,
    })
  })

  // 2) 임계값 초과 노드 → 노드 메뉴로 이동
  critNodes.forEach(n => {
    const crit = n.avg_value >= 90
    items.push({
      icon: crit ? '🔴' : '🟠',
      sevClass: crit ? 'danger' : 'warning',
      label: crit ? 'critical' : 'warning',
      title: `${n.node_name} CPU ${n.avg_value?.toFixed(1)}%`,
      time: '리소스 임계값 초과',
      onclick: `window.goToNodes()`,
    })
  })

  if (!items.length) {
    el.innerHTML = `
      <div class="card border-success">
        <div class="card-body py-2 text-success small">✅ 조치가 필요한 항목이 없습니다.</div>
      </div>`
    return
  }

  const LIMIT = 10
  const shown = items.slice(0, LIMIT)
  const overflow = items.length - shown.length

  el.innerHTML = `
    <div class="card">
      <div class="card-header fw-bold d-flex justify-content-between align-items-center">
        <span>⚠️ 조치 필요 항목</span>
        <span class="badge bg-danger">${items.length}</span>
      </div>
      <div class="list-group list-group-flush">
        ${shown.map(it => `
          <button type="button"
            class="list-group-item list-group-item-action d-flex justify-content-between align-items-center"
            onclick="${it.onclick}">
            <span>
              <span class="me-2">${it.icon}</span>
              <span class="badge bg-${it.sevClass} me-2">${it.label}</span>
              ${it.title}
            </span>
            <small class="text-muted">${it.time} ›</small>
          </button>
        `).join('')}
      </div>
      ${overflow > 0 ? `
        <button type="button" class="card-footer text-center small text-primary border-0 bg-transparent"
          onclick="window.goToEvents()">
          외 ${overflow}건 더 보기 →
        </button>` : ''}
    </div>
  `
}

// 이벤트 항목 클릭 → 이벤트 메뉴로 이동하며 해당 이벤트 상세를 자동으로 연다
window.goToEvent = (id) => {
  window.__openEventId = id
  location.hash = '#events'
}

// 노드 항목 클릭 → 노드 메뉴로 이동
window.goToNodes = () => {
  location.hash = '#nodes'
}

// '더 보기' → 이벤트 목록 메뉴로 이동
window.goToEvents = () => {
  location.hash = '#events'
}
