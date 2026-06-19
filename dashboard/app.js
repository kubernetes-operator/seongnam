import { API } from './api.js'
import { renderDashboard }   from './pages/dashboard.js'
import { renderNodes }       from './pages/nodes.js'
import { renderEvents }      from './pages/events.js'
import { renderPredictions } from './pages/predictions.js'
import { renderReports }     from './pages/reports.js'

let currentCluster = ''

const PAGES = {
  '#dashboard':   renderDashboard,
  '#nodes':       renderNodes,
  '#events':      renderEvents,
  '#predictions': renderPredictions,
  '#reports':     renderReports,
}

async function navigate() {
  const hash = location.hash || '#dashboard'
  const fn   = PAGES[hash]
  if (!fn) return

  // 네비 활성화
  document.querySelectorAll('.nav-link').forEach(el => {
    el.classList.toggle('active', el.getAttribute('href') === hash)
  })

  if (fn) await fn(currentCluster).catch(err => {
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

document.getElementById('cluster-select').addEventListener('change', e => {
  currentCluster = e.target.value
  navigate()
})

document.getElementById('refresh-btn').addEventListener('click', () => navigate())

document.getElementById('api-key-form').addEventListener('submit', e => {
  e.preventDefault()
  const key = document.getElementById('api-key-input').value
  localStorage.setItem('api_key', key)
  const modal = bootstrap.Modal.getInstance(document.getElementById('api-key-modal'))
  modal?.hide()
  loadClusters().then(navigate)
})

window.addEventListener('hashchange', navigate)

// 자동 새로고침 30초
setInterval(() => navigate(), 30000)

loadClusters().then(navigate)
