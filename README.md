# K8s OS Monitor

Kubernetes 클러스터의 Base OS 및 K8s 상태를 수집·저장·분석·예측·시각화하는 통합 모니터링 플랫폼.

## 아키텍처

```
Node Exporter/psutil ─┐
kubernetes-client   ──┼─→ Collector ─→ TimescaleDB ─→ FastAPI ─┬─→ CLI (Rich/Typer)
Loki (LogQL)         ─┘                    ↑                  ├─→ Web Dashboard (Chart.js)
                                     Crisis / Predictor         └─→ Reports (HTML/PDF/JSON)
```

- **수집**: OS 메트릭은 Node Exporter(Prometheus) 우선 조회, 부족한 항목(inode, zombie process 등)은 SSH로 보완. K8s 상태는 kubernetes-client-python으로 수집.
- **저장**: TimescaleDB(PostgreSQL)에 시계열 적재, hourly 연속 집계(Continuous Aggregate) 사용.
- **분석**: 임계값 기반 위기 감지(`crisis_engine`) + Loki 로그 연계 진단, 선형회귀/이동평균 기반 예측(`predictor`).
- **제공**: FastAPI REST API, Rich 기반 CLI, Chart.js 웹 대시보드, 일/주/월/연 리포트.
- **배포**: Kustomize(base + dev/prod overlay) 기반 GitOps, ArgoCD로 자동 동기화, Harbor 레지스트리, GitHub Actions(self-hosted runner) CI/CD.

## 디렉토리 구조

```
src/
  collector/    OS(psutil/SSH) + K8s(kubernetes-client) 수집기
  db/           TimescaleDB 스키마, 마이그레이션, 커넥션 풀, 쿼리
  analysis/     위기 감지(crisis_engine/crisis_catalog), 예측(predictor/predict_service)
  api/          FastAPI 앱, 라우터(clusters/metrics/events/reports/predictions)
  cli/          Typer/Rich CLI
  reports/      리포트 생성기
tests/
  unit/         ruff + pytest 단위 테스트
  integration/  TimescaleDB, Prometheus 연동 테스트
dashboard/      Chart.js + Bootstrap 5 정적 웹 대시보드
deploy/         Kustomize base/overlays, ArgoCD Application, nginx 설정
k8s/            수집기 Deployment, RBAC
.github/workflows/  CI(lint/test/build), CD(Harbor push + GitOps 태그 업데이트)
```

## 기술 스택

- **언어/런타임**: Python 3.11+
- **API**: FastAPI, uvicorn, slowapi(rate limiting)
- **DB**: TimescaleDB(PostgreSQL), asyncpg
- **수집**: kubernetes / kubernetes-asyncio, aiohttp(Prometheus), asyncssh(SSH 보완 수집)
- **CLI**: Typer, Rich
- **분석**: numpy
- **대시보드**: Chart.js, Bootstrap 5, Vanilla JS (빌드 도구 없음)
- **테스트**: pytest, pytest-asyncio, pytest-cov, httpx
- **배포**: Docker(multi-stage), Harbor, Kustomize, ArgoCD, GitHub Actions(actions-runner-controller)

## API

`src/api/main.py` 기준 엔드포인트:

| Prefix | 설명 |
|---|---|
| `/api/v1/clusters` | 클러스터 목록/상세 |
| `/api/v1/metrics` | OS/K8s 메트릭 조회 (시계열 포함) |
| `/api/v1/events` | 위기 이벤트 조회 |
| `/api/v1/reports` | 리포트 생성/다운로드 |
| `/api/v1/predictions` | 예측 데이터 조회 |
| `/healthz` | 헬스체크 |

인증은 API Key, CORS/Rate limiting 적용.

## CLI 명령어

`src/cli/main.py` (`monitor` 커맨드) 기준:

- `status <cluster>` — 클러스터 전체 상태 요약 (색상 임계값 표시)
- `nodes <cluster>` — 노드별 현황 (role/os_distro/kernel/cpu/mem)
- `os-metrics` — OS 메트릭 상세 조회
- `k8s` — K8s 리소스 상태 조회
- `top` — 리소스 사용량 상위 노드/파드
- `events` — 위기 이벤트 목록
- `predict` — 예측 결과 조회
- `report` — 리포트 생성 트리거

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

## 배포 (GitOps)

- `deploy/base` — 공통 매니페스트 (API/collector/dashboard Deployment, TimescaleDB StatefulSet, CronJob)
- `deploy/overlays/{dev,prod}` — 환경별 Kustomize 오버레이
- `deploy/argocd/application-prod.yaml` — ArgoCD Application CR (`deploy/` 디렉토리가 GitOps 단일 진실 소스)
- 이미지는 Harbor(`registry.local.cloud`)에 git SHA 태그로 푸시되며, CD 워크플로우가 GitOps 저장소의 이미지 태그를 갱신하면 ArgoCD가 자동 동기화한다.

```bash
kubectl apply -k deploy/overlays/prod
```

## CI/CD

- `.github/workflows/ci.yml` — PR 시 린트·테스트·이미지 빌드 검증
- `.github/workflows/cd.yml` — main 머지 시 Harbor 빌드/푸시 + GitOps 이미지 태그 업데이트
- Self-hosted runner는 클러스터 내 actions-runner-controller(ARC)로 운영

## 개발 하네스

이 프로젝트는 `harness@harness-marketplace` 플러그인으로 구성된 전용 에이전트/스킬 세트로 개발되었다 (`.claude/agents/`, `.claude/skills/`). 모니터링 시스템 관련 작업 시 `k8s-os-monitor` 오케스트레이터 스킬이 12개 Phase(수집→저장→분석→API→CLI→대시보드→리포트→QA→컨테이너→CI/CD→GitOps)로 작업을 조율한다. 자세한 내용은 `CLAUDE.md` 참고.
