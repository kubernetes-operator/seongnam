import { API } from './api.js'
import { renderDashboard }   from './pages/dashboard.js'
import { renderNodes }       from './pages/nodes.js'
import { renderEvents }      from './pages/events.js'
import { renderLogs }        from './pages/logs.js'
import { renderPredictions } from './pages/predictions.js'
import { renderReports }     from './pages/reports.js'
import { renderSettings }    from './pages/settings.js'

let currentCluster = ''

const PAGES = {
  '#dashboard':   renderDashboard,
  '#nodes':       renderNodes,
  '#events':      renderEvents,
  '#logs':        renderLogs,
  '#predictions': renderPredictions,
  '#reports':     renderReports,
  '#settings':    renderSettings,
}

const loginOverlay = document.getElementById('login-overlay')

function showLogin() {
  loginOverlay.hidden = false
  document.getElementById('logout-btn').hidden = true
  document.getElementById('current-user').textContent = ''
}
function hideLogin() { loginOverlay.hidden = true }

// api.js 가 401 을 만나면 호출 → 로그인 화면으로
window.__onAuthError = () => { showLogin() }

async function navigate() {
  const hash = location.hash || '#dashboard'
  const fn   = PAGES[hash] || renderDashboard

  document.querySelectorAll('#tabs .tab').forEach(el => {
    el.classList.toggle('active', el.dataset.hash === hash)
  })

  // 설정 페이지는 클러스터 불필요
  const arg = hash === '#settings' ? undefined : currentCluster
  await fn(arg).catch(err => {
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

// 인증 확인 후 앱 시작
async function boot() {
  const me = await API.auth.me().catch(() => null)
  if (!me?.data?.username) { showLogin(); return }
  hideLogin()
  document.getElementById('current-user').textContent = '👤 ' + me.data.username
  document.getElementById('logout-btn').hidden = false
  await loadClusters()
  await navigate()
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

// ── 로그인 / 로그아웃 ──
document.getElementById('login-form').addEventListener('submit', async e => {
  e.preventDefault()
  const err = document.getElementById('login-error')
  err.textContent = ''
  try {
    const res = await API.auth.login(
      document.getElementById('login-username').value,
      document.getElementById('login-password').value,
    )
    localStorage.setItem('session_token', res.data.token)
    document.getElementById('login-password').value = ''
    await boot()
  } catch {
    err.textContent = '사용자명 또는 비밀번호가 올바르지 않습니다.'
  }
})
document.getElementById('logout-btn').addEventListener('click', async () => {
  await API.auth.logout().catch(() => {})
  localStorage.removeItem('session_token')
  showLogin()
})

window.addEventListener('hashchange', navigate)

// ── 자동 새로고침 (기본 1분, 선택: 10초/30초/1분/10분/안함) ──
const DEFAULT_REFRESH_MS = 60000
let refreshTimer = null

function applyRefreshInterval() {
  const sel = document.getElementById('refresh-interval')
  const ms = Number(sel.value)
  if (refreshTimer) { clearInterval(refreshTimer); refreshTimer = null }
  localStorage.setItem('refresh_ms', String(ms))
  if (ms > 0) {
    refreshTimer = setInterval(() => { if (loginOverlay.hidden) navigate() }, ms)
  }
}

;(function initRefreshInterval() {
  const sel = document.getElementById('refresh-interval')
  const saved = localStorage.getItem('refresh_ms')
  sel.value = (saved !== null && [...sel.options].some(o => o.value === saved))
    ? saved : String(DEFAULT_REFRESH_MS)
  sel.addEventListener('change', applyRefreshInterval)
  applyRefreshInterval()
})()

boot()
