"""FastAPI 애플리케이션 진입점."""
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from api.dependencies import startup, shutdown
from api.routers import clusters, metrics, events, reports, predictions

limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await startup()
    yield
    await shutdown()


app = FastAPI(
    title="K8s OS Monitor API",
    version="1.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(clusters.router,    prefix="/api/v1/clusters",    tags=["clusters"])
app.include_router(metrics.router,     prefix="/api/v1/metrics",      tags=["metrics"])
app.include_router(events.router,      prefix="/api/v1/events",        tags=["events"])
app.include_router(reports.router,     prefix="/api/v1/reports",       tags=["reports"])
app.include_router(predictions.router, prefix="/api/v1/predictions",   tags=["predictions"])


@app.get("/healthz", tags=["health"])
async def health():
    return {"status": "ok"}
