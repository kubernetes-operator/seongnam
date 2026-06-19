"""Pydantic 요청/응답 모델."""
from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel


class ApiResponse(BaseModel):
    status: str = "success"
    data: Any = None
    meta: Optional[dict] = None
    error: Optional[dict] = None

    @classmethod
    def ok(cls, data: Any, meta: dict = None):
        return cls(status="success", data=data, meta=meta)

    @classmethod
    def err(cls, code: str, message: str):
        return cls(status="error", error={"code": code, "message": message})


class ReportGenerateRequest(BaseModel):
    report_type: str
    cluster_name: str
    output_formats: list[str] = ["json", "html"]


class EventResolveRequest(BaseModel):
    note: Optional[str] = None
