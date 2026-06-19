---
name: k8s-os-monitor
description: |
  Kubernetes 클러스터 OS 모니터링 시스템을 설계하고 구현하는 오케스트레이터 스킬. 'K8s 모니터링 시스템 만들어줘', 'OS 수집 시스템 구현', 'Kubernetes 운영 현황 시스템', '모니터링 플랫폼 구축', '리포트 시스템 구현', '위기 감지 시스템', '예측 시스템 구현', '모니터링 대시보드 구축', '하네스 다시 실행', '모니터링 업데이트', '에이전트 재실행' 등 모니터링 시스템 전반 또는 특정 구성 요소 구현 요청 시 이 스킬을 사용할 것.
---

# K8s OS Monitor — 오케스트레이터

## 시스템 개요

**목표**: Kubernetes 클러스터의 Base OS 및 K8s 상태를 수집·저장·분석·예측·시각화하는 통합 모니터링 플랫폼

**기술 스택**:
- 언어: Python 3.11+
- DB: TimescaleDB (PostgreSQL 확장)
- API: FastAPI + asyncpg
- CLI: Rich + Typer
- 대시보드: HTML + Chart.js + Bootstrap 5
- 배포: Kubernetes (DaemonSet + Deployment + CronJob)

**에이전트 팀 구성**:
| 에이전트 | 역할 | 스킬 |
|---------|------|------|
| os-collector | OS 메트릭 수집 | os-metrics |
| k8s-collector | K8s 상태 수집 | k8s-metrics |
| data-manager | DB 적재/조회 | db-operations |
| report-generator | 리포트 생성 | report-builder |
| crisis-analyzer | 위기 감지/분석 | crisis-detection |
| predictor | 트렌드 예측 | trend-prediction |
| api-server | FastAPI REST API | fastapi-builder |
| cli-interface | CLI 표 출력 | cli-table |
| dashboard | 웹 대시보드 | web-dashboard |

**실행 모드**: 하이브리드
- Phase 1~2 (수집): 병렬 서브 에이전트
- Phase 3~5 (분석·리포트): 에이전트 팀
- Phase 6~8 (인터페이스 구축): 병렬 서브 에이전트
- Phase 9~12 (QA·CI/CD·GitOps): 순차 서브 에이전트

---

## Phase 0: 컨텍스트 확인

시작 시 기존 구현 상태를 확인한다:

```
_workspace/ 존재 여부 확인
├── 없음 → 초기 구현 (Phase 1부터)
├── 있음 + 부분 수정 요청 → 해당 Phase만 재실행
└── 있음 + 새 요청 → _workspace를 _workspace_prev/로 이동 후 새 실행
```

---

## Phase 1: DB 스키마 & 인프라 기반 구축

**실행 모드**: 서브 에이전트 (순차)

**담당**: data-manager 에이전트

작업 목록:
1. TimescaleDB Kubernetes 배포 매니페스트 생성
   - StatefulSet + PVC (50Gi)
   - Service (ClusterIP)
   - Secret (DB 접속 정보)

2. 스키마 초기화 스크립트 생성 (`db-operations` 스킬 참조)
   - `os_metrics` hypertable
   - `k8s_metrics` hypertable
   - `cluster_nodes` 레지스트리
   - `events` 테이블
   - `reports` 테이블
   - 연속 집계 뷰 (1시간 단위)
   - 보존 정책 (원본 90일, 집계 1년)

3. DB 연결 풀 모듈 (`db/pool.py`)

**산출물**: `_workspace/01_db/` 디렉토리

---

## Phase 2: 메트릭 수집 레이어 구축

**실행 모드**: 병렬 서브 에이전트

os-collector와 k8s-collector를 동시에 구현한다.

### 2-A: OS 수집 (os-collector)
`os-metrics` 스킬 참조:
- `collector/os_collector.py` — OSMetricsCollector 클래스
- `collector/os_service.py` — asyncio 루프, DB 적재, 임계값 체크
- `k8s/daemonset-collector.yaml` — DaemonSet 배포 매니페스트
  - 환경변수: NODE_NAME (fieldRef), CLUSTER_NAME, DATABASE_URL
  - hostPID: true (프로세스 정보 접근)
  - resources: requests cpu=50m memory=128Mi

### 2-B: K8s 수집 (k8s-collector)
`k8s-metrics` 스킬 참조:
- `collector/k8s_collector.py` — K8sMetricsCollector 클래스
- `collector/k8s_service.py` — 다중 클러스터 수집 루프
- `k8s/deployment-k8s-collector.yaml` — Deployment (replicas: 1)
- `k8s/rbac.yaml` — ClusterRole + ClusterRoleBinding (read-only)
  - get/list/watch: nodes, pods, events, deployments, statefulsets
  - get/list: metrics.k8s.io/nodes, metrics.k8s.io/pods

**산출물**: `_workspace/02_collector/`

---

## Phase 3: 분석 레이어 구축

**실행 모드**: 병렬 서브 에이전트

### 3-A: 위기 분석 (crisis-analyzer)
`crisis-detection` 스킬 참조:
- `analysis/crisis_catalog.py` — 7가지 위기 유형 카탈로그 (HIGH_CPU, MEMORY_EXHAUSTION, DISK_FULL, HIGH_LOAD, CRASHLOOP_BACKOFF, NODE_NOT_READY, OOM_KILLED)
- `analysis/crisis_engine.py` — 임계값 감지, 로그 분석, 중복 억제
- `analysis/crisis_service.py` — 실시간 모니터링 루프
  - os-collector/k8s-collector의 임계값 초과 이벤트 구독
  - DB에 위기 이벤트 기록
  - 각 위기 유형별 즉각 조치 + 공식 문서 링크 포함

### 3-B: 예측 분석 (predictor)
`trend-prediction` 스킬 참조:
- `analysis/predictor.py` — TrendPredictor 클래스
  - 선형 회귀, IQR 이상치 제거
  - 7일/30일/90일 예측
  - 고갈 시점 예측 (days_to_full)
  - 신뢰도 평가 (high/medium/low)
- `analysis/predict_service.py` — 1일 1회 배치 예측 실행
- 권고 유형: capacity_expansion, optimization, scaling_prediction

**산출물**: `_workspace/03_analysis/`

---

## Phase 4: 리포트 생성 레이어 구축

**실행 모드**: 서브 에이전트

**담당**: report-generator

`report-builder` 스킬 참조:
- `reports/generator.py` — ReportGenerator 클래스
  - 일간: 시간별 집계, 24시간 분석
  - 주간: 일별 집계, 7일 트렌드
  - 월간: 일별 집계 + predictor 연동, SLA 계산
  - 연간: 월별 집계, 성장률 분석
- `reports/templates/report.html.j2` — Jinja2 HTML 템플릿
  - 헤더: 클러스터명, 기간, 생성 시각
  - OS 영역: CPU/MEM/DISK/Network/Load 시계열 그래프 (Chart.js)
  - K8s 영역: 노드 상태, 파드 현황, 리소스 요청 대비 사용량
  - 이벤트 섹션: 위기 목록 + 해결책
  - 권고 사항: predictor 결과
  - 모든 지표: 최대 대비 비율(%) 표시
- `k8s/cronjob-reports.yaml` — CronJob
  - 일간: `0 0 * * *` (매일 자정 UTC)
  - 주간: `5 0 * * 1` (월요일 자정)
  - 월간: `10 0 1 * *` (매월 1일)
  - 연간: `15 0 1 1 *` (매년 1월 1일)

**산출물**: `_workspace/04_reports/`

---

## Phase 5: API 서버 구축

**실행 모드**: 서브 에이전트

**담당**: api-server

`fastapi-builder` 스킬 참조:
- `api/main.py` — FastAPI 앱 진입점
- `api/dependencies.py` — DB 풀, API Key 인증
- `api/models.py` — Pydantic 요청/응답 모델
- `api/routers/` — 라우터 모음
  - `clusters.py`: GET /api/v1/clusters, GET /api/v1/clusters/{name}
  - `metrics.py`: GET /api/v1/metrics/os/{cluster}/{node}, GET /api/v1/metrics/k8s/{cluster}/{node}, GET /api/v1/metrics/summary/{cluster}, GET /api/v1/metrics/top
  - `reports.py`: GET /api/v1/reports, GET /api/v1/reports/{id}, GET /api/v1/reports/{id}/download, POST /api/v1/reports/generate
  - `events.py`: GET /api/v1/events, GET /api/v1/events/{id}, PATCH /api/v1/events/{id}/resolve
  - `predictions.py`: GET /api/v1/predictions/{cluster}, GET /api/v1/predictions/{cluster}/{node}
- `k8s/deployment-api.yaml` — Deployment (replicas: 2, HPA)
- `k8s/service-api.yaml` — Service + Ingress

**산출물**: `_workspace/05_api/`

---

## Phase 6: CLI 인터페이스 구축

**실행 모드**: 서브 에이전트

**담당**: cli-interface

`cli-table` 스킬 참조:
- `cli/main.py` — Typer + Rich CLI 도구
- 명령:
  - `k8s-monitor status [--cluster] [--watch]` — 클러스터 현황 표
  - `k8s-monitor nodes --cluster <name> [--area os|k8s|all] [--sort cpu|memory|disk|load]` — 노드 상세
  - `k8s-monitor os --cluster --node` — OS 영역 메트릭 표
  - `k8s-monitor k8s --cluster --node` — K8s 영역 메트릭 표
  - `k8s-monitor report list/show/generate` — 리포트 관리
  - `k8s-monitor events [--severity] [--unresolved]` — 이벤트 목록
  - `k8s-monitor predict --cluster [--horizon 30]` — 예측 결과
  - `k8s-monitor top --metric cpu|memory|disk [--limit 10]` — Top N 노드
- 모든 표: 최대 대비 비율 강조 (✅🟡🔴 색상)
- `setup.py` 또는 `pyproject.toml` — pip 설치 지원
- `~/.k8s-monitor/config.yaml` — API URL + Key 설정

**산출물**: `_workspace/06_cli/`

---

## Phase 7: 웹 대시보드 구축

**실행 모드**: 서브 에이전트

**담당**: dashboard

`web-dashboard` 스킬 참조:
- `dashboard/index.html` — SPA 진입점 (네비게이션, 클러스터 선택)
- `dashboard/api.js` — API 클라이언트 (fetch + Bearer 인증)
- `dashboard/app.js` — 해시 기반 SPA 라우터, 60초 자동 갱신
- `dashboard/pages/dashboard.js` — 메인 대시보드
  - 요약 카드 (클러스터 수, 노드 수, 위기 이벤트 수)
  - 클러스터별 CPU/MEM/DISK 게이지 (최대 대비 비율 시각화)
  - 노드 상태 테이블 (OS + K8s 영역 분리)
- `dashboard/pages/nodes.js` — 노드별 상세, 클릭 시 24시간 시계열 그래프
- `dashboard/pages/reports.js` — 일/주/월/연 탭, 리포트 목록, HTML/PDF 다운로드
- `dashboard/pages/events.js` — 위기 이벤트 카드 (즉각 조치 + 공식 문서 링크)
- `dashboard/pages/predictions.js` — 예측 시각화, 고갈 예상 타임라인, 권고 카드
- `dashboard/components/gauge.js` — 재사용 게이지 바 컴포넌트
- `k8s/deployment-dashboard.yaml` — nginx Deployment + ConfigMap (API URL 주입)

**산출물**: `_workspace/07_dashboard/`

---

## Phase 8: 통합 패키징

**실행 모드**: 서브 에이전트 (순차)

- `README.md` — 시스템 개요, 설치·배포 방법
- `k8s/namespace.yaml` — Namespace: k8s-monitor
- `k8s/kustomization.yaml` — 전체 리소스 통합 (kustomize)
- `requirements.txt` — 전체 Python 의존성
- `Dockerfile.api` — API 서버 이미지
- `Dockerfile.collector` — 수집기 이미지
- `.env.example` — 환경변수 목록

**산출물**: `_workspace/08_package/`

---

## Phase 9: QA 검증

**실행 모드**: 서브 에이전트 (순차)

**담당**: qa 에이전트

`qa-testing` 스킬 참조:
- `pytest.ini` + `.coveragerc` 생성
- `tests/unit/` — mock 기반 단위 테스트 작성
  - `test_os_collector.py` — Prometheus 응답 파싱, 노드 매핑, 임계값 알림
  - `test_k8s_collector.py` — metrics-server 파싱, CPU/메모리 단위 변환
  - `test_predictor.py` — 선형 회귀, IQR 이상치 제거, 예측값 범위
  - `test_crisis_catalog.py` — 7가지 위기 유형 구조 검증
  - `test_api.py` — FastAPI /health 엔드포인트, 인증 필요 엔드포인트
- `tests/integration/` — 실제 서비스 연동 테스트 작성
  - `test_prometheus.py` — Prometheus 접근 및 Node Exporter 8노드 확인
  - `test_loki.py` — Loki /ready 확인
  - `test_timescaledb.py` — 삽입/조회/삭제 사이클
- `Makefile` — lint, test-unit, test-integration 타깃

**통과 기준**: 린트 0 violations + 단위 테스트 커버리지 80% 이상

**산출물**: `_workspace/09_qa/`

---

## Phase 10: 컨테이너 이미지 빌드 구성

**실행 모드**: 서브 에이전트 (순차)

**담당**: container-builder 에이전트

`dockerfile-builder` 스킬 참조:
- `Dockerfile.api` — python:3.11-slim multi-stage, uvicorn, non-root appuser
- `Dockerfile.collector` — python:3.11-slim + openssh-client, non-root appuser
- `Dockerfile.dashboard` — nginx:1.25-alpine, entrypoint.sh API URL 주입
- `.dockerignore` — .git, tests, .env*, _workspace 제외
- `deploy/nginx.conf` — SPA 폴백 + 정적 캐시 설정
- `deploy/entrypoint.sh` — API_BASE_URL을 env.js에 기록
- `scripts/build-push.sh` — trivy 스캔 포함 빌드·푸시 스크립트

**산출물**: `_workspace/10_dockerfiles/`

---

## Phase 11: GitHub Actions CI/CD 워크플로우

**실행 모드**: 서브 에이전트 (순차)

**담당**: cicd-pipeline 에이전트

`github-actions` 스킬 참조:
- `.github/workflows/ci.yml` — PR 트리거: lint → unit tests → integration tests (경고) → docker build check
- `.github/workflows/cd.yml` — main 머지 트리거: Harbor 빌드+push → deploy/ 이미지 태그 업데이트 → git commit [skip ci]
- ARC(actions-runner-controller) 설치 명령 문서화
  - arc-systems namespace에 컨트롤러
  - arc-runners namespace에 runner scale set (min:1, max:5)
  - `runs-on: arc-runner-set` 사용
- GitHub Secrets 목록: `HARBOR_REGISTRY`, `HARBOR_USERNAME`, `HARBOR_PASSWORD`, `TEST_DATABASE_URL`
- 브랜치 보호 규칙 가이드

**산출물**: `_workspace/11_cicd/`

---

## Phase 12: GitOps 저장소 구성

**실행 모드**: 서브 에이전트 (순차)

**담당**: gitops-manager 에이전트

`argocd-gitops` 스킬 참조:
- `deploy/base/` — 전체 K8s 매니페스트 (namespace, timescaledb, api, collector, dashboard, cronjobs)
- `deploy/overlays/prod/kustomization.yaml` — 이미지 태그 관리 (CD에서 자동 업데이트)
- `deploy/overlays/prod/patch-replicas-prod.yaml` — API, Dashboard replicas: 2
- `deploy/overlays/dev/kustomization.yaml` — latest 태그, replicas: 1
- `deploy/argocd/application-prod.yaml` — ArgoCD Application CR (automated.prune+selfHeal)
- ArgoCD 설치 명령 문서화 (infra 노드 nodeSelector)
- Harbor imagePullSecret 생성 명령 (`kubectl create secret docker-registry`)

**산출물**: `_workspace/12_gitops/`

---

## 에이전트 팀 구성 (CI/CD 포함)

| 에이전트 | 역할 | 스킬 |
|---------|------|------|
| os-collector | OS 메트릭 수집 | os-metrics |
| k8s-collector | K8s 상태 수집 | k8s-metrics |
| data-manager | DB 적재/조회 | db-operations |
| report-generator | 리포트 생성 | report-builder |
| crisis-analyzer | 위기 감지/분석 | crisis-detection |
| predictor | 트렌드 예측 | trend-prediction |
| api-server | FastAPI REST API | fastapi-builder |
| cli-interface | CLI 표 출력 | cli-table |
| dashboard | 웹 대시보드 | web-dashboard |
| qa | 코드 품질 검증 | qa-testing |
| container-builder | Dockerfile + Harbor | dockerfile-builder |
| cicd-pipeline | GitHub Actions | github-actions |
| gitops-manager | ArgoCD + Kustomize | argocd-gitops |

---

## 데이터 흐름

```
[각 노드] ──DaemonSet──→ os-collector ──→ data-manager (TimescaleDB)
[K8s API] ──────────────→ k8s-collector ─→ data-manager (TimescaleDB)
                                                    ↓
                              crisis-analyzer ←─────┤ (실시간 임계값 감지)
                              predictor       ←─────┤ (일 1회 배치)
                              report-generator ←────┤ (스케줄 CronJob)
                                                    ↓
                                          api-server (FastAPI)
                                           ↙              ↘
                                      cli-interface   dashboard
```

---

## 에러 핸들링

| 실패 시나리오 | 처리 방법 |
|-------------|---------|
| DB 연결 실패 | 지수 백오프 3회 재시도, 이후 대기 (60초) |
| 노드 수집 실패 | 해당 노드 건너뜀, 다음 수집 주기에 재시도 |
| API 서버 오류 | 503 + Retry-After, HPA 스케일아웃 |
| 리포트 생성 실패 | 실패 기록 후 다음 스케줄에 재시도, HTML만 제공 |
| crisis 로그 접근 불가 | 메트릭 기반 진단만 수행, 로그 없음 명시 |

---

## 테스트 시나리오

### 정상 흐름
1. `k8s-monitor status` 실행 → 클러스터 현황 표 출력
2. 웹 대시보드 접속 → 노드 게이지 표시
3. `k8s-monitor report generate --type daily --cluster prod` → 리포트 생성
4. `/api/v1/metrics/summary/prod-cluster-01?period=weekly` → 주간 집계 반환

### 에러 흐름
1. 노드 수집 실패 → `failed_nodes` 목록에 기록, 나머지 노드 정상 수집
2. CPU > 90% 감지 → events 테이블에 HIGH_CPU 이벤트 기록, API/대시보드에 표시
3. Disk 30일 내 고갈 예측 → capacity_expansion 권고 생성, 월간 리포트에 포함

---

## 변경 이력

CLAUDE.md의 변경 이력 테이블에 기록한다.
