import { API } from '../api.js'

export async function renderReports(cluster) {
  const main = document.getElementById('main-content')
  if (!cluster) { main.innerHTML = '<p class="text-muted">클러스터를 선택하세요.</p>'; return }

  main.innerHTML = `
    <h5 class="mb-3">리포트 — <span class="text-primary">${cluster}</span></h5>
    <div class="mb-3">
      <select id="report-type" class="form-select form-select-sm d-inline-block w-auto me-2">
        <option value="daily">일간</option>
        <option value="weekly">주간</option>
        <option value="monthly">월간</option>
        <option value="yearly">연간</option>
      </select>
      <button class="btn btn-sm btn-primary" id="gen-btn">생성</button>
    </div>
    <div id="report-list"></div>
  `

  async function loadReports() {
    const res = await API.reports.list(cluster).catch(() => ({data:[]}))
    const rows = (res?.data || []).map(r => `<tr>
      <td>${r.report_type||''}</td>
      <td>${String(r.created_at||'').slice(0,16)}</td>
      <td>${r.period_start||''} ~ ${r.period_end||''}</td>
      <td>
        ${r.file_path ? `<a href="/api/v1/reports/${r.id}/download?fmt=html" target="_blank" class="btn btn-sm btn-outline-primary me-1">HTML</a>` : ''}
        ${r.file_path ? `<a href="/api/v1/reports/${r.id}/download?fmt=json" target="_blank" class="btn btn-sm btn-outline-secondary">JSON</a>` : ''}
      </td>
    </tr>`).join('')
    document.getElementById('report-list').innerHTML = `
      <div class="table-responsive">
        <table class="table table-sm">
          <thead class="table-light"><tr><th>유형</th><th>생성일시</th><th>기간</th><th>다운로드</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    `
  }

  document.getElementById('gen-btn').addEventListener('click', async () => {
    const t = document.getElementById('report-type').value
    const btn = document.getElementById('gen-btn')
    btn.disabled = true; btn.textContent = '생성 중...'
    await API.reports.generate(cluster, t).catch(() => null)
    setTimeout(() => { btn.disabled=false; btn.textContent='생성'; loadReports() }, 3000)
  })

  loadReports()
}
