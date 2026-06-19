---
name: fastapi-builder
description: |
  FastAPI 기반 REST API 서버를 구현한다. 라우터 분리, Pydantic 모델 검증, asyncpg 비동기 DB 쿼리, API Key 인증, Rate Limiting, OpenAPI 문서를 포함한 완성형 코드를 제공한다. 'FastAPI', 'REST API', 'API 서버', 'Pydantic', '비동기 API', '엔드포인트 구현' 관련 작업 시 반드시 이 스킬을 사용할 것.
---

# FastAPI Builder 스킬

## 프로젝트 구조

```
api/
├── main.py              # FastAPI 앱 진입점
├── dependencies.py      # 공통 의존성 (DB 풀, 인증)
├── models.py            # Pydantic 요청/응답 모델
├── routers/
│   ├── clusters.py
│   ├── metrics.py
│   ├── reports.py
│   ├── events.py
│   └── predictions.py
└── services/
    ├── metrics_service.py
    └── report_service.py
```

## 앱 초기화 (main.py)

```python
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from routers import clusters, metrics, reports, events, predictions
from dependencies import startup, shutdown

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="K8s OS Monitor API",
    description="Kubernetes 클러스터 OS 모니터링 REST API",
    version="1.0.0",
    docs_url="/docs",
    openapi_url="/openapi.json",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Authorization", "Content-Type"],
)

# 라우터 등록
app.include_router(clusters.router, prefix="/api/v1/clusters", tags=["clusters"])
app.include_router(metrics.router, prefix="/api/v1/metrics", tags=["metrics"])
app.include_router(reports.router, prefix="/api/v1/reports", tags=["reports"])
app.include_router(events.router, prefix="/api/v1/events", tags=["events"])
app.include_router(predictions.router, prefix="/api/v1/predictions", tags=["predictions"])

@app.on_event("startup")
async def on_startup():
    await startup()

@app.on_event("shutdown")
async def on_shutdown():
    await shutdown()

@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok", "version": "1.0.0"}
```

## 공통 의존성 (dependencies.py)

```python
import os
import asyncpg
from fastapi import Header, HTTPException, status

_pool: asyncpg.Pool = None

async def startup():
    global _pool
    _pool = await asyncpg.create_pool(
        dsn=os.environ["DATABASE_URL"],
        min_size=5, max_size=20,
        command_timeout=30,
    )

async def shutdown():
    if _pool:
        await _pool.close()

async def get_db() -> asyncpg.Pool:
    return _pool

# API Key 인증
VALID_API_KEYS = set(os.environ.get("API_KEYS", "").split(","))

async def verify_api_key(authorization: str = Header(...)):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer 토큰이 필요합니다.")
    token = authorization[7:]
    if token not in VALID_API_KEYS:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="유효하지 않은 API 키입니다.")
    return token
```

## 표준 응답 모델 (models.py)

```python
from pydantic import BaseModel
from typing import Any, Optional, Generic, TypeVar

T = TypeVar("T")

class ApiResponse(BaseModel):
    status: str = "success"
    data: Any = None
    meta: Optional[dict] = None
    error: Optional[dict] = None

class MetricQuery(BaseModel):
    metric: str
    start: str  # ISO 8601
    end: str
    interval: str = "1h"  # '1m', '1h', '1d', '7d'

class ReportGenerateRequest(BaseModel):
    report_type: str   # 'daily', 'weekly', 'monthly', 'yearly'
    cluster_name: str
    output_formats: list[str] = ["json", "html"]
```

## 라우터 패턴 (routers/metrics.py)

```python
from fastapi import APIRouter, Depends, Query
from slowapi import Limiter
from slowapi.util import get_remote_address
from dependencies import get_db, verify_api_key
from models import ApiResponse

router = APIRouter(dependencies=[Depends(verify_api_key)])
limiter = Limiter(key_func=get_remote_address)

@router.get("/summary/{cluster_name}", response_model=ApiResponse)
@limiter.limit("60/minute")
async def get_cluster_summary(
    request,  # slowapi를 위해 필수
    cluster_name: str,
    period: str = Query("daily", enum=["daily", "weekly", "monthly", "yearly"]),
    db=Depends(get_db),
):
    """
    클러스터 전체 메트릭 요약을 반환한다.
    최대 대비 사용률(usage_ratio)을 포함한다.
    """
    period_hours = {"daily": 24, "weekly": 168, "monthly": 720, "yearly": 8760}[period]
    sql = """
        SELECT
            node_name,
            avg(cpu_usage_ratio)    AS cpu_avg,
            max(cpu_usage_ratio)    AS cpu_max,
            avg(memory_usage_ratio) AS mem_avg,
            max(memory_usage_ratio) AS mem_max,
            avg(disk_usage_ratio)   AS disk_avg,
            max(disk_usage_ratio)   AS disk_max
        FROM os_metrics
        WHERE cluster_name = $1
          AND time > NOW() - ($2 || ' hours')::interval
        GROUP BY node_name
        ORDER BY cpu_avg DESC
    """
    rows = await db.fetch(sql, cluster_name, str(period_hours))
    return ApiResponse(data=[dict(r) for r in rows])

@router.get("/os/{cluster_name}/{node_name}", response_model=ApiResponse)
@limiter.limit("60/minute")
async def get_os_metrics(
    request,
    cluster_name: str,
    node_name: str,
    metric: str = Query(..., description="수집 메트릭 명 (cpu_usage_ratio 등)"),
    start: str = Query(...),
    end: str = Query(...),
    interval: str = Query("1h"),
    db=Depends(get_db),
):
    sql = """
        SELECT
            time_bucket($1::interval, time) AS bucket,
            avg(%s) AS avg_value,
            max(%s) AS max_value,
            min(%s) AS min_value
        FROM os_metrics
        WHERE cluster_name = $2 AND node_name = $3
          AND time BETWEEN $4::timestamptz AND $5::timestamptz
        GROUP BY bucket ORDER BY bucket
    """ % (metric, metric, metric)  # metric은 화이트리스트 검증 후 사용
    rows = await db.fetch(sql, interval, cluster_name, node_name, start, end)
    return ApiResponse(
        data=[{"time": r["bucket"].isoformat(), "avg": r["avg_value"], "max": r["max_value"]} for r in rows],
        meta={"cluster": cluster_name, "node": node_name, "metric": metric}
    )
```

## 에러 핸들러

```python
from fastapi import Request
from fastapi.responses import JSONResponse

@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"status": "error", "data": None, "error": {"code": "INTERNAL_ERROR", "message": str(exc)}}
    )
```

## Kubernetes 배포 (deployment.yaml)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: k8s-monitor-api
spec:
  replicas: 2
  selector:
    matchLabels:
      app: k8s-monitor-api
  template:
    metadata:
      labels:
        app: k8s-monitor-api
    spec:
      containers:
      - name: api
        image: k8s-monitor-api:latest
        ports:
        - containerPort: 8000
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: k8s-monitor-secrets
              key: database-url
        - name: API_KEYS
          valueFrom:
            secretKeyRef:
              name: k8s-monitor-secrets
              key: api-keys
        resources:
          requests:
            cpu: "100m"
            memory: "256Mi"
          limits:
            cpu: "500m"
            memory: "512Mi"
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 10
        readinessProbe:
          httpGet:
            path: /health
            port: 8000
```

## 의존성

```
fastapi>=0.110.0
uvicorn[standard]>=0.27.0
slowapi>=0.1.9
asyncpg>=0.29.0
pydantic>=2.6.0
```

## 실행

```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000 --workers 4
```
