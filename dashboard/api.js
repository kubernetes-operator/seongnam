/**
 * API 클라이언트 — window.API_BASE_URL 은 entrypoint.sh 가 주입
 */
const BASE = (window.API_BASE_URL || '').replace(/\/$/, '')

function _headers() {
  const token = localStorage.getItem('session_token') || ''
  return { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` }
}

function _check(res) {
  if (res.status === 401) {
    // 세션 만료/미인증 → 로그인 화면으로
    localStorage.removeItem('session_token')
    if (typeof window.__onAuthError === 'function') window.__onAuthError()
    throw new Error('인증이 필요합니다')
  }
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

async function _get(path) {
  return _check(await fetch(`${BASE}${path}`, { headers: _headers() }))
}

async function _post(path, body) {
  return _check(await fetch(`${BASE}${path}`, {
    method: 'POST', headers: _headers(), body: JSON.stringify(body || {}),
  }))
}

async function _patch(path) {
  return _check(await fetch(`${BASE}${path}`, { method: 'PATCH', headers: _headers() }))
}

export const API = {
  auth: {
    login:  (username, password) => _post('/api/v1/auth/login', { username, password }),
    logout: ()                   => _post('/api/v1/auth/logout'),
    me:     ()                   => _get('/api/v1/auth/me'),
    changePassword: (current_password, new_password) =>
      _post('/api/v1/auth/change-password', { current_password, new_password }),
  },
  clusters:    { list: () => _get('/api/v1/clusters') },
  cluster:     { get: (n) => _get(`/api/v1/clusters/${n}`) },
  nodes:       { list: (n) => _get(`/api/v1/clusters/${n}/nodes`) },
  metrics: {
    summary:   (c)               => _get(`/api/v1/metrics/summary/${c}`),
    timeseries:(c, n, m, h=24)   => _get(`/api/v1/metrics/os/${c}/${n}?metric=${m}&interval=1h`),
    top:       (c, m='cpu_usage_ratio', l=5) => _get(`/api/v1/metrics/top?cluster_name=${c}&metric=${m}&limit=${l}`),
  },
  events: {
    list:      (c, r=false, l=50) => _get(`/api/v1/events?cluster_name=${c}&resolved=${r}&limit=${l}`),
    get:       (id)               => _get(`/api/v1/events/${id}`),
    resolve:   (id)               => _patch(`/api/v1/events/${id}/resolve`),
  },
  reports: {
    list:      (c)     => _get(`/api/v1/reports?cluster_name=${c}`),
    generate:  (c, t)  => _post('/api/v1/reports/generate', { cluster_name: c, report_type: t, output_formats: ['html', 'json'] }),
  },
  predictions: {
    cluster:   (c)     => _get(`/api/v1/predictions/${c}`),
    node:      (c, n)  => _get(`/api/v1/predictions/${c}/${n}`),
  },
  logs: {
    list:     ({node='', priority='', q='', minutes=60, limit=100}={}) =>
      _get(`/api/v1/logs?minutes=${minutes}&limit=${limit}` +
        (node ? `&node_name=${encodeURIComponent(node)}` : '') +
        (priority ? `&priority=${priority}` : '') +
        (q ? `&q=${encodeURIComponent(q)}` : '')),
    summary:  (minutes=60)             => _get(`/api/v1/logs/summary?minutes=${minutes}`),
    patterns: (node='', minutes=60)    => _get(`/api/v1/logs/patterns?minutes=${minutes}` + (node ? `&node_name=${encodeURIComponent(node)}` : '')),
  },
}
