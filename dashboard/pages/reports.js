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
      <span id="gen-msg" class="muted"></span>
    </div>
    <div id="report-list"></div>
    <div id="report-view" style="margin-top:16px"></div>
  `

  async function loadReports() {
    const res = await API.reports.list(cluster).catch(() => ({ data: [] }))
    const rows = (res?.data || []).map(r => `<tr>
      <td>${r.report_type || ''}</td>
      <td><span class="badge" style="background:var(--card-bg);border:1px solid var(--border);color:var(--fg)">${(r.format || '').toUpperCase()}</span></td>
      <td>${String(r.created_at || '').slice(0, 16)}</td>
      <td>${String(r.period_start || '').slice(0,10)} ~ ${String(r.period_end || '').slice(0,10)}</td>
      <td>
        ${r.format === 'html' ? `<button class="btn-secondary btn-sm" onclick="window.viewReport(${r.id})" style="margin-right:4px">보기</button>` : ''}
        <button class="btn-secondary btn-sm" onclick="window.downloadReport(${r.id}, '${r.format}')">다운로드</button>
      </td>
    </tr>`).join('')
    document.getElementById('report-list').innerHTML = `
      <div class="table-wrap">
        <table class="findings-table">
          <thead><tr><th>유형</th><th>포맷</th><th>생성일시</th><th>기간</th><th>작업</th></tr></thead>
          <tbody>${rows || '<tr><td colspan="5" class="muted">생성된 리포트가 없습니다. 위에서 생성하세요.</td></tr>'}</tbody>
        </table>
      </div>
    `
  }

  // 화면에 표시(HTML을 iframe 으로 렌더)
  window.viewReport = async (id) => {
    const view = document.getElementById('report-view')
    view.innerHTML = '<div class="loading">불러오는 중…</div>'
    try {
      const html = await API.reports.raw(id, 'view')
      view.innerHTML = `
        <div class="card card-flush">
          <div class="card-header"><span>리포트 미리보기 #${id}</span>
            <button class="btn-secondary btn-sm" onclick="document.getElementById('report-view').innerHTML=''">닫기</button>
          </div>
          <iframe style="width:100%;height:600px;border:0;background:#fff" sandbox="allow-same-origin"></iframe>
        </div>`
      view.querySelector('iframe').srcdoc = html
    } catch (e) {
      view.innerHTML = `<div class="alert alert-danger">미리보기 실패: ${e.message}</div>`
    }
  }

  // 파일 다운로드(인증 헤더로 내용 fetch 후 blob 저장)
  window.downloadReport = async (id, fmt) => {
    try {
      const text = await API.reports.raw(id, 'download')
      const mime = fmt === 'html' ? 'text/html' : 'application/json'
      const blob = new Blob([text], { type: mime })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `report-${id}.${fmt}`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    } catch (e) {
      alert('다운로드 실패: ' + e.message)
    }
  }

  document.getElementById('gen-btn').addEventListener('click', async () => {
    const t = document.getElementById('report-type').value
    const btn = document.getElementById('gen-btn')
    const msg = document.getElementById('gen-msg')
    btn.disabled = true; btn.textContent = '생성 중...'; msg.textContent = ''
    try {
      await API.reports.generate(cluster, t)
      msg.className = 'text-ok'; msg.textContent = '✅ 생성되었습니다.'
    } catch (e) {
      msg.className = 'text-critical'; msg.textContent = '생성 실패: ' + e.message
    }
    btn.disabled = false; btn.textContent = '생성'
    loadReports()
  })

  await loadReports()
}
