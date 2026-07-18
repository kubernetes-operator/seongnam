# OS Monitor

Kubernetes 클러스터 노드의 Base OS 상태를 수집·저장·분석·예측·시각화하는 모니터링 플랫폼. (Kubernetes 리소스 자체의 상태 — 파드/디플로이먼트 등 — 는 모니터링 대상이 아니며, 순수 OS 메트릭만 다룬다. 플랫폼 자체는 Kubernetes 위에서 운영된다.)

## 아키텍처

```
Node Exporter/psutil ─┐
Loki (LogQL)         ─┴─→ Collector ─→ TimescaleDB ─→ FastAPI ─┬─→ CLI (Rich/Typer)
                                    ↑                           ├─→ Web Dashboard (Chart.js)
                             Crisis / Predictor                 └─→ Reports (HTML/PDF/JSON)
```

- **수집**: OS 메트릭은 Node Exporter(Prometheus) 우선 조회, 부족한 항목(inode, zombie process 등)은 SSH로 보완.
- **저장**: TimescaleDB(PostgreSQL)에 시계열 적재, hourly 연속 집계(Continuous Aggregate) 사용.
- **분석**: 임계값 기반 위기 감지(`crisis_engine`) + Loki 로그 연계 진단, 선형회귀/이동평균 기반 예측(`predictor`).
- **제공**: FastAPI REST API, Rich 기반 CLI, Chart.js 웹 대시보드, 일/주/월/연 리포트.
- **배포**: Kustomize(base + dev/prod overlay) 기반 GitOps 구조, Harbor 레지스트리, GitHub Actions CI/CD(설정은 되어 있으나 아래 CI/CD 항목의 주의사항 참고).

## 디렉토리 구조

```
src/
  collector/    OS(psutil/SSH) 수집기
  db/           TimescaleDB 스키마, 마이그레이션, 커넥션 풀, 쿼리
  analysis/     위기 감지(crisis_engine/crisis_catalog), 예측(predictor/predict_service)
  api/          FastAPI 앱, 라우터(clusters/metrics/events/reports/predictions)
  cli/          Typer/Rich CLI
  reports/      리포트 생성기
tests/
  unit/         ruff + pytest 단위 테스트
  integration/  TimescaleDB, Prometheus 연동 테스트
dashboard/      Chart.js + Bootstrap 5 정적 웹 대시보드 (SPA, API Key 모달 포함)
deploy/         Kustomize base/overlays, ArgoCD Application, nginx 설정, Gateway API HTTPRoute, PrometheusRule
scripts/        이미지 빌드·push 헬퍼 스크립트
.github/workflows/  CI(lint/test/build), CD(Harbor push + GitOps 태그 업데이트)
```

## 기술 스택

- **언어/런타임**: Python 3.11+
- **API**: FastAPI, uvicorn, slowapi(rate limiting)
- **DB**: TimescaleDB(PostgreSQL), asyncpg
- **수집**: aiohttp(Prometheus), asyncssh(SSH 보완 수집)
- **CLI**: Typer, Rich
- **분석**: numpy
- **대시보드**: Chart.js, Bootstrap 5, Vanilla JS (빌드 도구 없음)
- **테스트**: pytest, pytest-asyncio, pytest-cov, httpx
- **배포**: Docker(multi-stage), Harbor, Kustomize, ArgoCD(매니페스트만 준비됨, 아래 참고), GitHub Actions
- **인그레스**: NodePort + Gateway API(nginx Gateway Fabric)

## API

`src/api/main.py` 기준 엔드포인트:

| Prefix | 설명 |
|---|---|
| `/api/v1/clusters` | 클러스터 목록/상세 |
| `/api/v1/metrics` | OS 메트릭 조회 (시계열 포함) |
| `/api/v1/events` | 위기 이벤트 조회 |
| `/api/v1/reports` | 리포트 생성/다운로드 |
| `/api/v1/predictions` | 예측 데이터 조회 |
| `/healthz` | 헬스체크 — TimescaleDB에 `SELECT 1`을 실제로 실행해 DB 연결까지 확인한다 (실패 시 503). Kubernetes liveness/readiness probe와 Prometheus 알림이 이 응답에 의존한다. |

인증은 API Key(Bearer 토큰), CORS/Rate limiting 적용.

## CLI 명령어

`src/cli/main.py` (`monitor` 커맨드) 기준:

- `status <cluster>` — 클러스터 전체 상태 요약 (색상 임계값 표시)
- `nodes <cluster>` — 노드별 현황 (os_distro/kernel/cpu/mem)
- `os-metrics` — OS 메트릭 상세 조회
- `top` — 리소스 사용량 상위 노드/파드
- `events` — 위기 이벤트 목록
- `predict` — 예측 결과 조회
- `report` — 리포트 생성 트리거

## 웹 대시보드 접근

- **NodePort**: 클러스터 노드 IP + `:30605` (구성에 따라 다를 수 있음, `deploy/base/dashboard/deployment.yaml`/Service 참고)
- **Gateway API**: `https://test2.studiobasa.com/osmonitoring/` (`deploy/base/dashboard/httproute.yaml`, 클러스터의 공용 nginx Gateway에 붙는다)
- 두 진입점 모두 같은 대시보드 파드로 연결되며, `window.API_BASE_URL`이 `/osmonitoring`으로 고정 주입되어 있어 어느 경로로 들어와도 API 프록시가 동일하게 동작한다.
- 최초 접속 시 좌측 사이드바 **"🔑 API Key"** 버튼으로 API Key를 입력해야 클러스터/메트릭 데이터가 조회된다 (키를 입력하기 전에는 모든 API 호출이 401/403으로 실패해 화면에 데이터가 뜨지 않는다).

## 헬스체크 및 모니터링 알림

- `os-monitor-api`, `os-monitor-dashboard` Deployment 모두 liveness/readinessProbe 설정됨 (API는 `/healthz`가 DB 연결까지 검사).
- `deploy/base/dashboard/prometheusrule.yaml` — 클러스터의 기존 kube-state-metrics를 이용해 `OSMonitorAPIDown`/`OSMonitorDashboardDown` 알림 규칙 정의 (별도 exporter 불필요, Prometheus Operator의 PrometheusRule CRD 사용, `release: prometheus-stack` 라벨로 자동 인식됨).
- **주의**: 이 클러스터의 Alertmanager는 현재 실제 수신자(Slack/이메일/webhook 등)가 구성되어 있지 않다 (`receiver: null`). 알림 규칙은 평가되지만 실제로 어디에도 전달되지 않으므로, 알림을 받으려면 Alertmanager 설정에 수신자를 추가해야 한다.

## 로컬 개발

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

cp .env.example .env   # DATABASE_URL, API_KEY 등 채우기

make migrate            # TimescaleDB 스키마 적용
make run-api             # FastAPI 개발 서버 (포트 8000)
make run-collector       # 수집기 단독 실행
```

## 테스트

```bash
make lint               # ruff
make test-unit          # pytest + coverage (tests/unit)
make test-integration   # TimescaleDB/Prometheus 연동 (INTEGRATION_TEST=1)
make cov                # HTML 커버리지 리포트 (htmlcov/index.html)
```

## 배포

- **네임스페이스**: `os-monitor` (`deploy/base/kustomization.yaml`의 전역 `namespace` 필드)
- `deploy/base` — 공통 매니페스트 (API/collector/dashboard Deployment, TimescaleDB StatefulSet, CronJob, HTTPRoute, PrometheusRule)
- `deploy/overlays/{dev,prod}` — 환경별 Kustomize 오버레이
- `deploy/argocd/application-prod.yaml` — ArgoCD Application CR (아직 클러스터에 ArgoCD 자체가 설치되어 있지 않음 — 현재는 `kubectl apply -k`로 수동 배포)
- 이미지: Harbor(`registry.local.cloud:5000/os-monitor/{api,collector,dashboard}`)

### 최초 배포 순서 (네임스페이스가 없는 상태에서)

```bash
kubectl create namespace os-monitor

# Secret은 git에 없음 — 직접 생성 (DATABASE_URL, API_KEY는 자격 증명이므로 별도 관리)
kubectl create secret generic os-monitor-db-secret -n os-monitor \
  --from-literal=DATABASE_URL=postgresql://monitor:<password>@timescaledb.os-monitor.svc.cluster.local:5432/monitor \
  --from-literal=POSTGRES_USER=monitor \
  --from-literal=POSTGRES_PASSWORD=<password>
kubectl create secret generic os-monitor-api-secret -n os-monitor \
  --from-literal=API_KEY=<key>

# 이미지 빌드·push (CI가 아직 동작하지 않으면 수동으로 — 아래 CI/CD 참고)
bash scripts/build-push-images.sh

kubectl apply -k deploy/base
```

이미지나 nginx 설정(`deploy/nginx.conf`)이 바뀐 뒤에는 `scripts/build-push-images.sh` 재실행 후 `kubectl rollout restart deployment/<name> -n os-monitor`가 필요하다 (`:latest` 태그라 재배포 없이는 새 이미지를 자동으로 당겨오지 않는다).

## CI/CD

- `.github/workflows/ci.yml` — PR 시 린트·테스트·이미지 빌드 검증
- `.github/workflows/cd.yml` — main 머지 시 Harbor 빌드/푸시 + GitOps 이미지 태그 업데이트
- Self-hosted runner는 클러스터 내 actions-runner-controller(ARC)로 운영하도록 설계되어 있으나, **현재 클러스터에는 ARC 컨트롤러만 설치되어 있고 실제 `AutoscalingRunnerSet`(러너 스케일셋)은 배포되어 있지 않다.** 그 결과 push된 워크플로우가 `queued` 상태로 멈춰 실행되지 않으므로, 러너가 준비되기 전까지는 `scripts/build-push-images.sh`로 수동 빌드·push해야 한다.

## 개발 하네스

이 프로젝트는 `harness@harness-marketplace` 플러그인으로 구성된 전용 에이전트/스킬 세트로 개발되었다 (`.claude/agents/`, `.claude/skills/`). 모니터링 시스템 관련 작업 시 `os-monitor` 오케스트레이터 스킬이 12개 Phase(수집→저장→분석→API→CLI→대시보드→리포트→QA→컨테이너→CI/CD→GitOps)로 작업을 조율한다. 자세한 내용은 `CLAUDE.md` 참고.
