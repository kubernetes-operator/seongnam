import { API } from '../api.js'

const sevClass = (p) => (['emerg', 'alert', 'crit', 'error'].includes(p) ? 'text-critical'
  : p === 'warning' ? 'text-warning' : 'muted')

export async function renderLogs(cluster) {
  const main = document.getElementById('main-content')
  if (!cluster) { main.innerHTML = '<p class="muted">클러스터를 선택하세요.</p>'; return }

  main.innerHTML = `
    <h2>시스템 로그 <span class="muted" style="font-size:13px">(호스트 systemd journal)</span></h2>
    <div class="filters">
      <label>노드 <input type="text" id="log-node" placeholder="전체" style="width:140px"></label>
      <label>우선순위
        <select id="log-priority" class="select-sm">
          <option value="">전체</option>
          <option value="error">error+</option>
          <option value="warning">warning</option>
          <option value="notice">notice</option>
          <option value="info">info</option>
        </select>
      </label>
      <label>기간
        <select id="log-minutes" class="select-sm">
          <option value="15">15분</option>
          <option value="60" selected>1시간</option>
          <option value="360">6시간</option>
          <option value="1440">24시간</option>
        </select>
      </label>
      <label>검색 <input type="text" id="log-q" placeholder="본문 검색" style="width:160px"></label>
      <button class="btn-primary btn-sm" id="log-apply">조회</button>
    </div>

    <div id="log-summary" class="cards"></div>

    <h3>탐지된 이상 시그니처</h3>
    <div id="log-patterns"><div class="loading">불러오는 중…</div></div>

    <h3 style="margin-top:20px">최근 로그</h3>
    <div id="log-table"><div class="loading">불러오는 중…</div></div>
  `

  const opts = () => ({
    node: document.getElementById('log-node').value.trim(),
    priority: document.getElementById('log-priority').value,
    minutes: Number(document.getElementById('log-minutes').value),
    q: document.getElementById('log-q').value.trim(),
  })

  async function load() {
    const { node, priority, minutes, q } = opts()
    const [sum, pats, list] = await Promise.all([
      API.logs.summary(minutes),
      API.logs.patterns(node, minutes),
      API.logs.list({ node, priority, q, minutes, limit: 200 }),
    ]).catch(() => [null, { data: [] }, { data: [] }])

    // 요약 카드
    const s = sum?.data || {}
    const byP = s.by_priority || {}
    document.getElementById('log-summary').innerHTML = `
      <div class="card"><div class="card-title">전체 (${s.window_minutes || minutes}분)</div><div style="font-size:22px">${s.total ?? 0}</div></div>
      <div class="card"><div class="card-title">경고 이상</div><div style="font-size:22px" class="text-warning">${s.warning_plus ?? 0}</div></div>
      <div class="card"><div class="card-title">error</div><div style="font-size:22px" class="text-critical">${byP.error || 0}</div></div>
      <div class="card"><div class="card-title">노드 수</div><div style="font-size:22px">${Object.keys(s.by_node || {}).length}</div></div>
    `

    // 탐지 시그니처
    const patterns = pats?.data || []
    document.getElementById('log-patterns').innerHTML = patterns.length ? `
      <div class="table-wrap"><table class="findings-table">
        <thead><tr><th>심각도</th><th>유형</th><th>노드</th><th>건수</th><th>샘플</th></tr></thead>
        <tbody>${patterns.map(p => `<tr>
          <td><span class="sev-pill ${p.severity === 'critical' ? 'sev-critical' : 'sev-warning'}">${p.severity}</span></td>
          <td>${p.label}</td>
          <td>${(p.nodes && p.nodes.length)
            ? p.nodes.map(n => `<span class="badge" style="background:var(--card-bg);border:1px solid var(--border);color:var(--fg);margin:1px">${n.node || '?'} <span class="muted">${n.count}</span></span>`).join(' ')
            : '<span class="muted">-</span>'}</td>
          <td class="${p.severity === 'critical' ? 'text-critical fw-bold' : 'text-warning'}">${p.count}</td>
          <td><code style="font-size:11px">${(p.samples[0] || '').replace(/</g, '&lt;')}</code></td>
        </tr>`).join('')}</tbody>
      </table></div>` : '<p class="text-ok">✅ 탐지된 이상 시그니처가 없습니다.</p>'

    // 최근 로그
    const lines = list?.data || []
    document.getElementById('log-table').innerHTML = `
      <div class="table-wrap"><table class="findings-table">
        <thead><tr><th>시각</th><th>노드</th><th>유닛</th><th>우선순위</th><th>메시지</th></tr></thead>
        <tbody>${lines.map(l => `<tr>
          <td style="white-space:nowrap">${new Date(l.ts * 1000).toLocaleString('ko-KR', { hour12: false })}</td>
          <td>${l.node_name}</td>
          <td class="muted">${(l.unit || '').replace(/\.service$/, '')}</td>
          <td class="${sevClass(l.priority)}">${l.priority}</td>
          <td style="font-family:ui-monospace,monospace;font-size:12px">${(l.message || '').replace(/</g, '&lt;')}</td>
        </tr>`).join('') || '<tr><td colspan="5" class="muted">로그가 없습니다.</td></tr>'}</tbody>
      </table></div>`
  }

  document.getElementById('log-apply').addEventListener('click', load)
  document.getElementById('log-q').addEventListener('keydown', e => { if (e.key === 'Enter') load() })
  await load()
}
