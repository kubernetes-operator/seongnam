import { API } from './api.js'
import { renderDashboard }   from './pages/dashboard.js'
import { renderNodes }       from './pages/nodes.js'
import { renderEvents }      from './pages/events.js'
import { renderLogs }        from './pages/logs.js'
import { renderPredictions } from './pages/predictions.js'
import { renderReports }     from './pages/reports.js'

let currentCluster = ''

const PAGES = {
  '#dashboard':   renderDashboard,
  '#nodes':       renderNodes,
  '#events':      renderEvents,
  '#logs':        renderLogs,
  '#predictions': renderPredictions,
  '#reports':     renderReports,
}

async function navigate() {
  const hash = location.hash || '#dashboard'
  const fn   = PAGES[hash] || renderDashboard

  // 탭 활성화
  document.querySelectorAll('#tabs .tab').forEach(el => {
    el.classList.toggle('active', el.dataset.hash === hash)
  })

  await fn(currentCluster).catch(err => {
    document.getElementById('main-content').innerHTML =
      `<div class="alert alert-danger">로드 실패: ${err.message}</div>`
  })
}

async function loadClusters() {
  const select = document.getElementById('cluster-select')
  const res = await API.clusters.list().catch(() => null)
  const clusters = res?.data || []
  select.innerHTML = '<option value="">클러스터 선택</option>' +
    clusters.map(c => `<option value="${c.cluster_name}">${c.cluster_name}</option>`).join('')
  if (clusters.length) {
    currentCluster = clusters[0].cluster_name
    select.value   = currentCluster
  }
}

// ── 탭/홈 내비게이션 ──
document.querySelectorAll('#tabs .tab').forEach(btn => {
  btn.addEventListener('click', () => { location.hash = btn.dataset.hash })
})
document.getElementById('home-link').addEventListener('click', () => { location.hash = '#dashboard' })

document.getElementById('cluster-select').addEventListener('change', e => {
  currentCluster = e.target.value
  navigate()
})
document.getElementById('refresh-btn').addEventListener('click', () => navigate())

// ── API Key 모달 ──
const modal = document.getElementById('api-key-modal')
const openModal  = () => { document.getElementById('api-key-input').value = localStorage.getItem('api_key') || ''; modal.hidden = false }
const closeModal = () => { modal.hidden = true }
document.getElementById('api-key-btn').addEventListener('click', openModal)
document.getElementById('api-key-cancel').addEventListener('click', closeModal)
modal.addEventListener('click', e => { if (e.target === modal) closeModal() })
document.getElementById('api-key-form').addEventListener('submit', e => {
  e.preventDefault()
  localStorage.setItem('api_key', document.getElementById('api-key-input').value)
  closeModal()
  loadClusters().then(navigate)
})

window.addEventListener('hashchange', navigate)

// 자동 새로고침 30초
setInterval(() => navigate(), 30000)

loadClusters().then(navigate)
