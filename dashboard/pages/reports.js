import { API } from '../api.js'

export async function renderReports(cluster) {
  const main = document.getElementById('main-content')
  if (!cluster) { main.innerHTML = '<p class="muted">클러스터를 선택하세요.</p>'; return }

  main.innerHTML = `
    <h2>리포트 — <span style="color:var(--info)">${cluster}</span></h2>
    <div class="toolbar">
      <select id="report-type" class="select-sm">
        <option value="daily">일간</option>
        <option value="weekly">주간</option>
        <option value="monthly">월간</option>
        <option value="yearly">연간</option>
      </select>
      <button class="btn-primary btn-sm" id="gen-btn">생성</button>
    </div>
    <div id="report-list"></div>
  `

  async function loadReports() {
    const res = await API.reports.list(cluster).catch(() => ({ data: [] }))
    const rows = (res?.data || []).map(r => `<tr>
      <td>${r.report_type || ''}</td>
      <td>${String(r.created_at || '').slice(0, 16)}</td>
      <td>${r.period_start || ''} ~ ${r.period_end || ''}</td>
      <td>
        ${r.file_path ? `<a href="/api/v1/reports/${r.id}/download?fmt=html" target="_blank" class="btn-secondary btn-sm" style="margin-right:4px">HTML</a>` : ''}
        ${r.file_path ? `<a href="/api/v1/reports/${r.id}/download?fmt=json" target="_blank" class="btn-secondary btn-sm">JSON</a>` : ''}
      </td>
    </tr>`).join('')
    document.getElementById('report-list').innerHTML = `
      <div class="table-wrap">
        <table class="findings-table">
          <thead><tr><th>유형</th><th>생성일시</th><th>기간</th><th>다운로드</th></tr></thead>
          <tbody>${rows || '<tr><td colspan="4" class="muted">생성된 리포트가 없습니다.</td></tr>'}</tbody>
        </table>
      </div>
    `
  }

  document.getElementById('gen-btn').addEventListener('click', async () => {
    const t = document.getElementById('report-type').value
    const btn = document.getElementById('gen-btn')
    btn.disabled = true; btn.textContent = '생성 중...'
    try {
      await API.reports.generate(cluster, t)
    } catch (e) {
      alert('리포트 생성 실패: ' + e.message)
    }
    btn.disabled = false; btn.textContent = '생성'
    loadReports()
  })

  await loadReports()
}
