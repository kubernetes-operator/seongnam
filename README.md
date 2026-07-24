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
- **로그**: 호스트 systemd journal을 전용 promtail로 Loki에 적재하고, `log_service`가 LogQL로 조회·요약·이상 시그니처 탐지 (아래 "시스템 로그 분석" 참고).
- **분석**: 임계값 기반 위기 감지(`crisis_engine`) + Loki 로그 연계 진단, 선형회귀/이동평균 기반 예측(`predictor`).
- **제공**: FastAPI REST API, Rich 기반 CLI, 웹 대시보드(`/ai/seoul` 기본 페이지 스타일), 일/주/월/연 리포트.
- **배포**: Kustomize(base + dev/prod overlay) 기반 GitOps. 이미지는 이 서버에서 수동 빌드·push 후 태그를 git에 커밋하면 **ArgoCD가 자동 동기화·배포**한다 (GitHub Actions/ARC는 제거됨 — 아래 CI/CD 참고).

## 모니터링 대상

Base OS 상태만 다룬다. **Kubernetes 리소스 자체(파드/디플로이먼트/서비스 등)의 상태는 대상이 아니다.**

### OS 메트릭 (Prometheus/Node Exporter, 60초 주기)

| 범주 | 수집 항목 | 임계값 (warning / critical) |
|------|-----------|------------------------------|
| **CPU** | 사용률(`usage_ratio`), iowait(%) | 80% / 90% |
| **Memory** | 사용률, 사용 바이트, swap 사용률 | 80% / 90% |
| **Disk** | 루트(`/`) 사용률, read/write B/s | 75% / 90% |
| **Network** | rx/tx B/s (`lo` 제외) | — (추세 관찰) |
| **Load** | load1/5/15, `load_per_core` | 1.5 / 2.0 (코어당) |
| **보완(SSH)** | CPU 코어 수, 좀비 프로세스 수, inode 사용률, uptime | — |

임계값 초과 시 `crisis_engine`이 위기 이벤트를 생성하고 관련 로그를 함께 첨부한다.

### 시스템 로그 (Loki / systemd journal)

- 각 노드의 **호스트 systemd journal** 전량 (우선순위 `emerg`~`debug`, systemd `unit`별, `node_name`별).
- **이상 시그니처 9종 자동 탐지**: OOM Kill, 커널 패닉/Oops, 디스크 I/O 오류, 파일시스템 오류, 디스크 공간 부족, segfault, hung task/soft lockup, 인증 실패(브루트포스 의심), 서비스 기동 실패.

## 수집 구조

```
                                  ┌──────────────── 메트릭 경로 ────────────────┐
  Node Exporter (전 노드)  ──PromQL──▶  Prometheus  ──┐
                                                       ├─▶  Collector(Deployment, 60초 루프)
  각 노드 SSH(kwlee@<ip>) ──보완수집──────────────────┘         │  (inode/zombie/uptime/cores)
                                                                ▼
                                                         TimescaleDB (hypertable + hourly CAGG)
                                                                │
                                  ┌──────────────── 로그 경로 ─────────────────┐│
  각 노드 /var/log/journal ─▶ os-journal-promtail(DaemonSet) ─▶ Loki           ││
                                        (job=systemd-journal)      ▲            ││
                                                                   │ LogQL      ▼▼
                                              log_service ─────────┘        FastAPI ─▶ CLI / 대시보드 / 리포트
                                              crisis_engine ───(로그 증거)──────┘

  CronJob:  predict(매일 02:30)   report-daily(매일 01:00)
```

- **메트릭**: `os_collector`가 기존 Prometheus(Node Exporter)에 **PromQL**로 질의 → 새 DaemonSet 없이 CPU/Mem/Disk/Net/Load 수집. OS 배포판·커널은 `node_os_info`(pretty_name)·`node_uname_info`(release) info 메트릭의 라벨에서 추출. Prometheus에 없는 항목(inode, 좀비 프로세스, uptime, 코어 수)은 `os_ssh`가 `kwlee@<node-ip>` SSH로 보완(SSH 키 미제공 환경에서는 이 보완만 생략됨). `os_service`가 이를 60초마다 합쳐 TimescaleDB에 적재하고 임계값을 검사한다.
- **로그**: 전용 `os-journal-promtail` DaemonSet이 각 노드의 영구 저널(`/var/log/journal`)을 읽어 Loki로 전송(`job="systemd-journal"`). `log_service`가 LogQL로 조회·요약·시그니처 탐지하고, `crisis_engine`은 위기 발생 시 관련 로그를 증거로 첨부한다. (로그는 Loki 자체 보존을 사용하며 TimescaleDB에 중복 저장하지 않는다.)
- **저장**: 메트릭 시계열은 TimescaleDB 하이퍼테이블 + hourly 연속 집계. 로그는 Loki.
- **제공**: FastAPI가 위 데이터를 REST로 노출하고, CLI·웹 대시보드·리포트가 이를 소비한다.

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
dashboard/      정적 웹 대시보드 (SPA, 빌드 도구 없음). 커스텀 CSS(css/style.css) + Chart.js(게이지), API Key 모달 포함
deploy/         Kustomize base/overlays, ArgoCD Application + 서브패스 노출(proxy/httproute), nginx 설정, Gateway API HTTPRoute, PrometheusRule
scripts/        이미지 빌드·push 헬퍼 스크립트
```

## 기술 스택

- **언어/런타임**: Python 3.11+
- **API**: FastAPI, uvicorn, slowapi(rate limiting)
- **DB**: TimescaleDB(PostgreSQL), asyncpg
- **수집**: aiohttp(Prometheus), asyncssh(SSH 보완 수집)
- **CLI**: Typer, Rich
- **분석**: numpy
- **대시보드**: Vanilla JS + 커스텀 CSS(`/ai/seoul` 기본 페이지 스타일, 라이트/다크 테마), Chart.js(게이지) — 빌드 도구 없음
- **테스트**: pytest, pytest-asyncio, pytest-cov, httpx
- **배포**: Docker(multi-stage), Harbor, Kustomize, ArgoCD(클러스터에 설치·가동 중)
- **인그레스**: NodePort + Gateway API(NGINX Gateway Fabric)

## API

`src/api/main.py` 기준 엔드포인트:

| Prefix | 설명 |
|---|---|
| `/api/v1/clusters` | 클러스터 목록/상세 |
| `/api/v1/metrics` | OS 메트릭 조회 (시계열 포함) |
| `/api/v1/events` | 위기 이벤트 조회 |
| `/api/v1/reports` | 리포트 생성/다운로드 |
| `/api/v1/predictions` | 예측 데이터 조회 |
| `/api/v1/logs` | 시스템 로그 조회(`/`), 요약(`/summary`), 이상 시그니처 탐지(`/patterns`) — Loki(systemd journal) 기반 |
| `/api/v1/auth` | 로그인(`/login`), 로그아웃(`/logout`), 현재 사용자(`/me`), 비밀번호 변경(`/change-password`) |
| `/healthz` | 헬스체크 — TimescaleDB에 `SELECT 1`을 실제로 실행해 DB 연결까지 확인한다 (실패 시 503). Kubernetes liveness/readiness probe와 Prometheus 알림이 이 응답에 의존한다. |

**인증**: 사용자명+비밀번호 로그인 → 세션 토큰(Bearer). 비밀번호는 PBKDF2-HMAC-SHA256 + per-user salt로 `users` 테이블에 저장(평문 없음), 세션은 `sessions` 테이블. 최초 기동 시 기본 관리자 **`admin` / `password`** 시드(⚠️ **즉시 변경 필수** — 설정 탭 또는 `ADMIN_USERNAME`/`ADMIN_PASSWORD` env로 재정의). CORS/Rate limiting 적용.

## CLI 명령어

`src/cli/main.py` (`monitor` 커맨드) 기준:

- `status <cluster>` — 클러스터 전체 상태 요약 (색상 임계값 표시)
- `nodes <cluster>` — 노드별 현황 (os_distro/kernel/cpu/mem)
- `os-metrics` — OS 메트릭 상세 조회
- `top` — 리소스 사용량 상위 노드/파드
- `events` — 위기 이벤트 목록
- `predict` — 예측 결과 조회
- `report` — 리포트 생성 트리거
- `logs` — 호스트 시스템 로그 조회 + 이상 시그니처 탐지 (Loki/journald)

## 웹 대시보드 접근

- **NodePort**: 클러스터 노드 IP + `:30605` (구성에 따라 다를 수 있음, `deploy/base/dashboard/deployment.yaml`/Service 참고)
- **Gateway API**: `https://test2.studiobasa.com/osmonitoring/` (`deploy/base/dashboard/httproute.yaml`, 클러스터의 공용 nginx Gateway에 붙는다)
- 두 진입점 모두 같은 대시보드 파드로 연결되며, `window.API_BASE_URL`이 `/osmonitoring`으로 고정 주입되어 있어 어느 경로로 들어와도 API 프록시가 동일하게 동작한다 (`entrypoint.sh`가 index.html의 `window.API_BASE_URL = ''` 문자열을 치환).
- UI는 `/ai/seoul`(k8s-cluster-tester) 기본 페이지 스타일 — 상단 **topbar + 수평 탭**(개요/노드/이벤트/로그/예측/리포트/설정), 라이트/다크 테마 자동 대응. 좌측 상단 **"OS Monitor"** 클릭 시 개요(메인)로 이동.
- 최초 접속 시 **로그인 화면**에서 사용자명+비밀번호 입력(기본 `admin`/`password` — 즉시 변경). 로그인 후 세션 토큰이 발급되며, 우상단에 현재 사용자와 **로그아웃** 버튼이 표시된다. **설정** 탭에서 비밀번호를 변경할 수 있다(변경 시 기존 세션 전부 무효화 → 재로그인).

## 시스템 로그 분석 (Loki / systemd journal)

메트릭 외에 **호스트 Linux 시스템 로그**를 수집·분석한다.

- **수집**: `deploy/logging/host-journal-promtail.yaml` — 각 노드의 영구 저널(`/var/log/journal`)을 읽어 Loki에 `job="systemd-journal"`(라벨 `node_name`/`unit`/`priority`)로 전송하는 전용 promtail DaemonSet. (클러스터 기본 promtail은 파드 로그만 수집하므로 호스트 OS 로그용으로 별도 배포. `logging` 네임스페이스, ArgoCD 관리 대상 아님 → `kubectl apply -f`로 배포/갱신.)
- **분석**: `src/analysis/log_service.py` — LogQL로 최근 로그 / 우선순위·노드별 요약 / 알려진 이상 시그니처(OOM·커널패닉·I/O·파일시스템·디스크·segfault·hung task·인증실패·서비스실패) 탐지.
- **제공**: `/api/v1/logs*` API, 대시보드 **"로그" 탭**(필터·요약카드·탐지패턴·로그테이블), CLI `monitor logs`.
- **주의(민감정보)**: 저널에는 인증 로그 등 개인정보가 포함될 수 있다. 대시보드는 우선순위/시그니처 중심으로 표시하며, 필요 시 promtail 파이프라인에서 필터링을 추가할 것.

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
- `deploy/argocd/` — ArgoCD Application(`application-prod.yaml`) + 서버 파라미터·서브패스 노출(`argocd-cmd-params-cm.yaml`, `proxy.yaml`, `httproute.yaml`, `README.md`). **ArgoCD는 클러스터에 설치·가동 중**이며 `os-monitor-prod` Application이 `deploy/overlays/prod`를 auto-sync(+selfHeal+prune)로 배포한다.
- 이미지: Harbor(`registry.local.cloud:5000/os-monitor/{api,collector,dashboard}`)
- ArgoCD UI: `https://test2.studiobasa.com/argocd/` (자세한 노출 구조는 `deploy/argocd/README.md`)

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

# 이미지 빌드·push (아래 CI/CD 참고 — 이 서버에서 수동 빌드)
bash scripts/build-push-images.sh

kubectl apply -k deploy/base   # 최초 1회. 이후 변경은 ArgoCD가 자동 반영
```

### 변경 배포 흐름 (ArgoCD GitOps)

```bash
# 1) 이 서버에서 이미지 빌드·push (Harbor 로그인 필요)
SHA=$(git rev-parse --short HEAD)
docker build -f Dockerfile.dashboard -t registry.local.cloud:5000/os-monitor/dashboard:$SHA .
docker push registry.local.cloud:5000/os-monitor/dashboard:$SHA

# 2) deploy/overlays/prod/kustomization.yaml 의 해당 이미지 newTag 를 $SHA 로 갱신·커밋·push
# 3) ArgoCD가 자동 동기화하여 롤아웃 (auto-sync + selfHeal)
```

`newTag`를 git SHA로 고정하므로 `:latest` 재배포 문제 없이 ArgoCD가 정확한 버전을 롤아웃한다.

## CI/CD

- **GitHub Actions는 제거되었다.** (이전 `.github/workflows/{ci,cd}.yml` + actions-runner-controller(ARC) 자체호스팅 러너 구성은 삭제됨 — 러너 스케일셋 미배포로 워크플로우가 계속 `queued`에 멈추던 문제 + 미숙지 기술 제거 요청.)
- 현재 파이프라인: **이 서버에서 수동 이미지 빌드·push → kustomize 태그 커밋 → ArgoCD 자동 배포**. 사내 Harbor(`registry.local.cloud:5000`)는 내부망이라 외부 러너로는 접근 불가하므로 빌드는 클러스터 접근이 가능한 이 서버에서 수행한다.

## 개발 하네스

이 프로젝트는 `harness@harness-marketplace` 플러그인으로 구성된 전용 에이전트/스킬 세트로 개발되었다 (`.claude/agents/`, `.claude/skills/`). 모니터링 시스템 관련 작업 시 `os-monitor` 오케스트레이터 스킬이 12개 Phase(수집→저장→분석→API→CLI→대시보드→리포트→QA→컨테이너→CI/CD→GitOps)로 작업을 조율한다. 자세한 내용은 `CLAUDE.md` 참고.

## 변경 내역

| 날짜 | 변경 내용 |
|------|-----------|
| 2026-07-17 | K8s 상태 모니터링 기능 제거 → **OS Monitor**로 스코프 확정·개명. 배포 네임스페이스 `monitoring` → `os-monitor`. |
| 2026-07-18 | 대시보드를 Gateway API로 `/osmonitoring` 노출, 브라우저 캐싱 비활성화, `/healthz` DB 연결 검사 + liveness/readiness probe + PrometheusRule 알림 추가. |
| 2026-07-24 | 대시보드 개요에 **"조치 필요 항목"** 패널 추가(미해결 위기 이벤트 + 임계값 초과 노드, 성능 섹션 하단·최대 10개·클릭 시 해당 메뉴 이동), 사이드바 "OS Monitor" 클릭 시 홈 이동. |
| 2026-07-24 | **GitHub Actions/ARC 제거** → 수동 이미지 빌드 + **ArgoCD GitOps** 배포로 전환. git remote의 **GitHub PAT 평문 노출 제거**(gh 자격증명 헬퍼 경유). |
| 2026-07-24 | **ArgoCD 클러스터 설치·가동**, `https://test2.studiobasa.com/argocd/` 노출(서브패스 base-href 교정용 nginx 프록시 포함). |
| 2026-07-24 | **대시보드 UI 전면 재설계** — Bootstrap 제거, `/ai/seoul`(k8s-cluster-tester) 기본 페이지 스타일(topbar+탭, 라이트/다크 테마) 도입. |
| 2026-07-24 | **Linux 시스템 로그 수집·분석 추가** — 호스트 systemd journal → Loki(전용 promtail), `log_service`(요약·이상 시그니처 9종), `/api/v1/logs*`, 대시보드 "로그" 탭, CLI `monitor logs`. |
| 2026-07-24 | **인증을 사용자명+비밀번호 로그인 체계로 교체**(기존 단일 API Key) — `/api/v1/auth`, `users`/`sessions` 테이블, 세션 토큰, 대시보드 로그인 화면·설정(비밀번호 변경) 탭. 기본 `admin`/`password` 시드. |
| 2026-07-24 | 노드 탭 **OS/커널 표시 수정** — `node_os_info`/`node_uname_info`에서 수집(수집기 Pod의 SSH 인증 불가로 SSH 보완이 동작하지 않던 문제 우회). 로그 이상 시그니처에 **노드별 발생 건수 표기** 추가. |
| 2026-07-24 | **예측을 14일 미만 데이터에서도 표시**(현재값 기반 추정치 + 신뢰도 등급 low/very_low, 예측 탭에 신뢰도 열). **리포트 다운로드/미리보기 수정** — 내용을 DB(`reports.content`)에 저장해 API 다중 Pod/CronJob 간 공유 문제 해결, 대시보드에서 인증 fetch→blob 다운로드 + HTML iframe 미리보기(보기/다운로드 버튼). |
| 2026-07-24 | **이벤트 발생 시각 표시 수정** — events 테이블 컬럼은 `time`인데 대시보드가 없는 `created_at`을 참조해 시각이 공백이던 버그 수정(목록·상세·개요 조치항목, 로컬 시각 포맷). |

> 하네스(에이전트/스킬) 구성 변경 이력은 `CLAUDE.md`의 변경 이력 표를 참고.
