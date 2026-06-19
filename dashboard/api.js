/**
 * API 클라이언트 — window.API_BASE_URL 은 entrypoint.sh 가 주입
 */
const BASE = (window.API_BASE_URL || '').replace(/\/$/, '')

function _headers() {
  const key = localStorage.getItem('api_key') || ''
  return { 'Content-Type': 'application/json', 'Authorization': `Bearer ${key}` }
}

async function _get(path) {
  const res = await fetch(`${BASE}${path}`, { headers: _headers() })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

async function _post(path, body) {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: _headers(),
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

async function _patch(path) {
  const res = await fetch(`${BASE}${path}`, { method: 'PATCH', headers: _headers() })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

export const API = {
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
}
