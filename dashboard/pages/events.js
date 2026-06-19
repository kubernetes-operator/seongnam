import { API } from '../api.js'

export async function renderEvents(cluster) {
  const main = document.getElementById('main-content')
  if (!cluster) { main.innerHTML = '<p class="text-muted">클러스터를 선택하세요.</p>'; return }

  main.innerHTML = `
    <h5 class="mb-3">위기 이벤트 — <span class="text-primary">${cluster}</span></h5>
    <div class="mb-2">
      <div class="form-check form-switch d-inline-block me-3">
        <input class="form-check-input" type="checkbox" id="show-resolved">
        <label class="form-check-label" for="show-resolved">해결됨 포함</label>
      </div>
    </div>
    <div id="events-table"></div>
    <div id="event-detail" class="mt-3"></div>
  `

  async function loadEvents() {
    const resolved = document.getElementById('show-resolved')?.checked || false
    const evts = await API.events.list(cluster, resolved, 50).catch(() => ({data:[]}))
    const rows = (evts?.data || []).map(ev => {
      const d = typeof ev.details === 'string' ? JSON.parse(ev.details||'{}') : (ev.details||{})
      const sev = ev.severity || ''
      const sevClass = sev==='critical' ? 'danger' : 'warning'
      return `<tr style="cursor:pointer" onclick="window.showEvent(${ev.id})">
        <td>${ev.id}</td>
        <td><span class="badge bg-${sevClass}">${sev}</span></td>
        <td>${d.crisis_type||ev.event_type||''}</td>
        <td>${ev.node_name||''}</td>
        <td>${String(ev.created_at||'').slice(0,16)}</td>
        <td>${ev.resolved_at ? '✅' : '<button class="btn btn-sm btn-outline-success" onclick="event.stopPropagation();window.resolveEvent('+ev.id+')">해결</button>'}</td>
      </tr>`
    }).join('')
    document.getElementById('events-table').innerHTML = `
      <div class="table-responsive">
        <table class="table table-sm table-hover">
          <thead class="table-light">
            <tr><th>ID</th><th>심각도</th><th>유형</th><th>노드</th><th>시각</th><th>상태</th></tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    `
  }

  window.showEvent = async (id) => {
    const ev = await API.events.get(id).catch(() => null)
    if (!ev?.data) return
    const d = typeof ev.data.details === 'string' ? JSON.parse(ev.data.details||'{}') : (ev.data.details||{})
    const cat = ev.data.catalog || {}
    document.getElementById('event-detail').innerHTML = `
      <div class="card">
        <div class="card-header fw-bold">이벤트 #${id} 상세</div>
        <div class="card-body">
          <p><b>위기유형:</b> ${d.crisis_type||''}</p>
          <p><b>설명:</b> ${cat.description||''}</p>
          <p><b>즉각조치:</b></p>
          <ul>${(cat.immediate_actions||[]).map(a=>`<li><code>${a}</code></li>`).join('')}</ul>
          <p><b>참조:</b> ${(cat.references||[]).map(r=>`<a href="${r.url}" target="_blank">${r.title}</a>`).join(', ')}</p>
          ${d.log_samples?.length ? `<p><b>로그 샘플:</b></p><pre class="bg-light p-2 small">${d.log_samples.slice(0,5).join('\n')}</pre>` : ''}
        </div>
      </div>
    `
  }

  window.resolveEvent = async (id) => {
    await API.events.resolve(id).catch(() => null)
    loadEvents()
  }

  document.getElementById('show-resolved').addEventListener('change', loadEvents)
  loadEvents()
}
