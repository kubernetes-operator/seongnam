---
name: web-dashboard
description: |
  Chart.js + Bootstrap 5 + Vanilla JavaScript로 Kubernetes OS 모니터링 웹 대시보드를 구현한다. 빌드 도구 없이 정적 HTML/JS로 구성하며, SPA 라우팅, 자동 갱신, 게이지 바, 시계열 그래프, 리포트 다운로드, 이벤트 카드, 예측 시각화를 포함한다. '웹 대시보드', '모니터링 UI', 'Chart.js', 'HTML 대시보드', '웹 인터페이스' 관련 구현 시 반드시 이 스킬을 사용할 것.
---

# Web Dashboard 스킬

## 파일 구조

```
dashboard/
├── index.html          # SPA 진입점
├── app.js              # 라우터 + 상태 관리
├── api.js              # API 클라이언트
├── pages/
│   ├── dashboard.js    # 메인 대시보드
│   ├── nodes.js        # 노드 현황
│   ├── reports.js      # 리포트
│   ├── events.js       # 위기 이벤트
│   └── predictions.js  # 예측
└── components/
    ├── gauge.js        # 게이지 바 컴포넌트
    └── table.js        # 데이터 테이블 컴포넌트
```

## 메인 HTML (index.html)

```html
<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>K8s OS Monitor</title>
  <!-- Bootstrap 5 -->
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
  <!-- Chart.js -->
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
  <style>
    :root {
      --color-ok: #22c55e;
      --color-warn: #f59e0b;
      --color-crit: #ef4444;
    }
    body { background: #0f172a; color: #e2e8f0; }
    .navbar { background: #1e293b !important; border-bottom: 1px solid #334155; }
    .card { background: #1e293b; border: 1px solid #334155; }
    .card-header { background: #0f172a; border-bottom: 1px solid #334155; }

    /* 게이지 바 */
    .gauge-bar { height: 8px; background: #334155; border-radius: 4px; overflow: hidden; }
    .gauge-fill { height: 100%; border-radius: 4px; transition: width 0.5s ease; }
    .gauge-ok   { background: var(--color-ok); }
    .gauge-warn { background: var(--color-warn); }
    .gauge-crit { background: var(--color-crit); animation: pulse 1s infinite; }
    @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.6; } }

    /* 상태 뱃지 */
    .badge-ok   { background: rgba(34,197,94,.2); color: var(--color-ok); border: 1px solid var(--color-ok); }
    .badge-warn { background: rgba(245,158,11,.2); color: var(--color-warn); border: 1px solid var(--color-warn); }
    .badge-crit { background: rgba(239,68,68,.2); color: var(--color-crit); border: 1px solid var(--color-crit); }

    /* 테이블 */
    .table { color: #e2e8f0; }
    .table thead th { border-color: #334155; color: #94a3b8; font-size: .8rem; text-transform: uppercase; }
    .table tbody tr:hover { background: rgba(255,255,255,.04); }
    .table td { border-color: #1e293b; vertical-align: middle; }

    /* 이벤트 카드 */
    .event-card { border-left: 4px solid; padding: 12px 16px; margin: 8px 0; border-radius: 0 8px 8px 0; background: #1e293b; }
    .event-critical { border-color: var(--color-crit); }
    .event-warning  { border-color: var(--color-warn); }
  </style>
</head>
<body>
  <!-- 네비게이션 -->
  <nav class="navbar navbar-dark">
    <div class="container-fluid">
      <span class="navbar-brand fw-bold">⚡ K8s OS Monitor</span>
      <div class="d-flex align-items-center gap-3">
        <select id="clusterSelect" class="form-select form-select-sm" style="width:200px;background:#0f172a;color:#e2e8f0;border-color:#334155"></select>
        <span id="lastUpdated" class="text-muted small"></span>
      </div>
      <ul class="navbar-nav flex-row gap-3">
        <li><a class="nav-link" href="#/" data-route="dashboard">대시보드</a></li>
        <li><a class="nav-link" href="#/nodes" data-route="nodes">노드</a></li>
        <li><a class="nav-link" href="#/reports" data-route="reports">리포트</a></li>
        <li><a class="nav-link" href="#/events" data-route="events">이벤트</a></li>
        <li><a class="nav-link" href="#/predictions" data-route="predictions">예측</a></li>
      </ul>
    </div>
  </nav>
  <div id="app" class="container-fluid py-3"></div>

  <script src="api.js"></script>
  <script src="components/gauge.js"></script>
  <script src="pages/dashboard.js"></script>
  <script src="pages/nodes.js"></script>
  <script src="pages/reports.js"></script>
  <script src="pages/events.js"></script>
  <script src="pages/predictions.js"></script>
  <script src="app.js"></script>
</body>
</html>
```

## API 클라이언트 (api.js)

```javascript
const API = {
  baseUrl: window.ENV_API_URL || 'http://localhost:8000',
  apiKey: window.ENV_API_KEY || '',

  async get(path, params = {}) {
    const url = new URL(this.baseUrl + path);
    Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
    const resp = await fetch(url, {
      headers: { 'Authorization': `Bearer ${this.apiKey}` }
    });
    if (!resp.ok) throw new Error(`API 오류: ${resp.status}`);
    return resp.json();
  },

  async getClusters() { return this.get('/api/v1/clusters'); },
  async getClusterSummary(cluster, period = 'daily') {
    return this.get(`/api/v1/metrics/summary/${cluster}`, { period });
  },
  async getEvents(params = {}) { return this.get('/api/v1/events', params); },
  async getPredictions(cluster) { return this.get(`/api/v1/predictions/${cluster}`); },
};
```

## 게이지 컴포넌트 (components/gauge.js)

```javascript
function renderGauge(container, value, label) {
  const level = value >= 90 ? 'crit' : value >= 75 ? 'warn' : 'ok';
  const icon  = value >= 90 ? '🔴' : value >= 75 ? '🟡' : '✅';
  container.innerHTML = `
    <div class="d-flex justify-content-between mb-1">
      <small class="text-muted">${label}</small>
      <small class="fw-bold text-${level === 'crit' ? 'danger' : level === 'warn' ? 'warning' : 'success'}">
        ${icon} ${value?.toFixed(1) ?? 'N/A'}%
      </small>
    </div>
    <div class="gauge-bar">
      <div class="gauge-fill gauge-${level}" style="width:${Math.min(value ?? 0, 100)}%"></div>
    </div>
  `;
}
```

## 대시보드 페이지 (pages/dashboard.js)

```javascript
async function renderDashboard(cluster) {
  const app = document.getElementById('app');
  app.innerHTML = '<div class="text-center py-5"><div class="spinner-border text-primary"></div></div>';

  const [summary, events] = await Promise.all([
    API.getClusterSummary(cluster, 'daily'),
    API.getEvents({ cluster_name: cluster, resolved: 'false', limit: 5 }),
  ]);

  const nodes = summary.data || [];
  const critCount = (events.data || []).filter(e => e.severity === 'critical').length;

  app.innerHTML = `
    <!-- 요약 카드 -->
    <div class="row g-3 mb-4">
      <div class="col-md-3">
        <div class="card">
          <div class="card-body text-center">
            <div class="h2 mb-0">${nodes.length}</div>
            <small class="text-muted">총 노드</small>
          </div>
        </div>
      </div>
      <div class="col-md-3">
        <div class="card">
          <div class="card-body text-center">
            <div class="h2 mb-0 ${critCount > 0 ? 'text-danger' : 'text-success'}">${critCount}</div>
            <small class="text-muted">위험 이벤트</small>
          </div>
        </div>
      </div>
    </div>

    <!-- 노드별 리소스 게이지 -->
    <div class="card mb-4">
      <div class="card-header">노드별 리소스 사용률 (최대 대비 비율)</div>
      <div class="card-body">
        <table class="table table-sm">
          <thead>
            <tr>
              <th>노드</th><th>CPU 평균</th><th>CPU 최대</th>
              <th>MEM 평균</th><th>MEM 최대</th><th>DISK 평균</th>
            </tr>
          </thead>
          <tbody>
            ${nodes.map(n => `
              <tr>
                <td class="fw-bold">${n.node_name}</td>
                <td><span class="${ratioBadge(n.cpu_avg)}">${n.cpu_avg?.toFixed(1) ?? 'N/A'}%</span></td>
                <td><span class="${ratioBadge(n.cpu_max)}">${n.cpu_max?.toFixed(1) ?? 'N/A'}%</span></td>
                <td><span class="${ratioBadge(n.mem_avg)}">${n.mem_avg?.toFixed(1) ?? 'N/A'}%</span></td>
                <td><span class="${ratioBadge(n.mem_max)}">${n.mem_max?.toFixed(1) ?? 'N/A'}%</span></td>
                <td><span class="${ratioBadge(n.disk_avg)}">${n.disk_avg?.toFixed(1) ?? 'N/A'}%</span></td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    </div>
  `;
}

function ratioBadge(v) {
  if (v == null) return 'badge badge-secondary';
  if (v >= 90) return 'badge badge-crit';
  if (v >= 75) return 'badge badge-warn';
  return 'badge badge-ok';
}
```

## Kubernetes 배포 (nginx)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: k8s-monitor-dashboard
spec:
  replicas: 2
  template:
    spec:
      containers:
      - name: nginx
        image: nginx:alpine
        volumeMounts:
        - name: dashboard
          mountPath: /usr/share/nginx/html
        - name: config
          mountPath: /etc/nginx/conf.d
      volumes:
      - name: config
        configMap:
          name: dashboard-env
```

ConfigMap으로 API URL 주입:
```javascript
// 빌드 시 env.js 생성
window.ENV_API_URL = 'http://k8s-monitor-api.default.svc.cluster.local';
window.ENV_API_KEY = '${API_KEY}';
```
