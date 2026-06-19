# K8s OS Monitor — 아키텍처 참조

## 전체 컴포넌트 구성

```
k8s-monitor/                        # 프로젝트 루트
├── collector/
│   ├── os_collector.py             # OSMetricsCollector (psutil 기반)
│   ├── os_service.py               # DaemonSet 수집 루프
│   ├── k8s_collector.py            # K8sMetricsCollector (kubernetes-client)
│   └── k8s_service.py              # 다중 클러스터 수집 루프
├── analysis/
│   ├── crisis_catalog.py           # 위기 유형 카탈로그
│   ├── crisis_engine.py            # 임계값 감지 + 로그 분석
│   ├── crisis_service.py           # 실시간 모니터링 루프
│   ├── predictor.py                # TrendPredictor (선형 회귀)
│   └── predict_service.py          # 배치 예측 서비스
├── reports/
│   ├── generator.py                # ReportGenerator (Jinja2, Chart.js)
│   └── templates/
│       └── report.html.j2          # HTML 리포트 템플릿
├── api/
│   ├── main.py                     # FastAPI 앱
│   ├── dependencies.py             # DB 풀, 인증
│   ├── models.py                   # Pydantic 모델
│   └── routers/
│       ├── clusters.py
│       ├── metrics.py
│       ├── reports.py
│       ├── events.py
│       └── predictions.py
├── cli/
│   ├── main.py                     # Typer + Rich CLI
│   └── config.yaml.example
├── dashboard/
│   ├── index.html
│   ├── api.js
│   ├── app.js
│   ├── pages/
│   └── components/
├── db/
│   ├── schema.py                   # 스키마 SQL
│   └── pool.py                     # asyncpg 풀
└── k8s/
    ├── namespace.yaml
    ├── secret-db.yaml
    ├── statefulset-timescaledb.yaml
    ├── service-timescaledb.yaml
    ├── daemonset-collector.yaml    # OS 수집기
    ├── deployment-k8s-collector.yaml
    ├── deployment-api.yaml
    ├── hpa-api.yaml
    ├── deployment-dashboard.yaml
    ├── service-api.yaml
    ├── service-dashboard.yaml
    ├── ingress.yaml
    ├── rbac.yaml
    ├── cronjob-daily-report.yaml
    ├── cronjob-weekly-report.yaml
    ├── cronjob-monthly-report.yaml
    ├── cronjob-yearly-report.yaml
    └── kustomization.yaml
```

## Kubernetes 리소스 요약

| 리소스 | 종류 | 역할 |
|--------|------|------|
| timescaledb | StatefulSet | TimescaleDB 데이터베이스 |
| os-collector | DaemonSet | 각 노드에서 OS 메트릭 수집 |
| k8s-collector | Deployment | Kubernetes API 메트릭 수집 |
| k8s-monitor-api | Deployment | REST API 서버 |
| k8s-monitor-dashboard | Deployment | 웹 대시보드 (nginx) |
| report-daily/weekly/monthly/yearly | CronJob | 정기 리포트 생성 |

## 포트 구성

| 서비스 | 포트 | 설명 |
|--------|------|------|
| TimescaleDB | 5432 | PostgreSQL 호환 DB |
| API 서버 | 8000 | FastAPI REST API |
| 대시보드 | 80 | nginx 정적 파일 |

## 환경변수

| 변수 | 설명 | 예시 |
|------|------|------|
| DATABASE_URL | TimescaleDB 접속 URL | postgresql://user:pass@timescaledb:5432/k8s_monitor |
| API_KEYS | 쉼표 구분 API 키 목록 | key1,key2 |
| CLUSTER_NAME | 현재 클러스터 이름 (수집기) | prod-cluster-01 |
| NODE_NAME | 현재 노드 이름 (DaemonSet, fieldRef) | node-01 |
| REPORT_OUTPUT_DIR | 리포트 파일 저장 경로 | /reports |
| COLLECTION_INTERVAL_SEC | 수집 주기 (초) | 60 |

## 지표 정의

모든 비율 지표는 **최대 대비 사용률(%)**:
- `cpu_usage_ratio` = 실제 CPU 사용% (0~100)
- `memory_usage_ratio` = 사용 메모리 / 전체 메모리 × 100
- `disk_usage_ratio` = 사용 디스크 / 전체 디스크 × 100
- `cpu_usage_ratio` (K8s) = 실제 사용 CPU / Allocatable CPU × 100
- `memory_usage_ratio` (K8s) = 실제 사용 메모리 / Allocatable 메모리 × 100
- `cpu_request_ratio` = 요청 CPU / Allocatable CPU × 100

## 임계값 기준

| 지표 | Warning | Critical |
|------|---------|----------|
| CPU 사용률 | > 80% | > 90% |
| Memory 사용률 | > 80% | > 90% |
| Disk 사용률 | > 75% | > 90% |
| Load / 코어 | > 1.5 | > 2.0 |
| K8s CPU 사용률 | > 75% | > 90% |
| K8s Memory 사용률 | > 80% | > 90% |
