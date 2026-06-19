---
name: trend-prediction
description: |
  시계열 메트릭 데이터를 분석하여 미래 리소스 사용량을 예측하고, 용량 계획 권고와 최적화 제안을 생성하는 Python 코드를 구현한다. 선형 회귀, 이동 평균, 계절성 분석을 사용한다. '예측', '트렌드 분석', '용량 계획', '리소스 고갈', '미래 상태', 'Capacity Planning' 관련 구현 시 반드시 이 스킬을 사용할 것.
---

# Trend Prediction 스킬

## 예측 엔진 구현

```python
# predictor.py
import statistics
from datetime import datetime, timezone, timedelta
from typing import Optional

class TrendPredictor:
    """시계열 메트릭으로 미래 상태를 예측한다."""

    MIN_DATA_POINTS = 14  # 최소 14일 데이터 필요

    def predict_metric(
        self,
        time_series: list[dict],  # [{"time": "...", "avg": 45.2}, ...]
        horizon_days: int = 30,
        metric_name: str = "metric",
    ) -> dict:
        """
        단일 메트릭의 미래 값을 예측한다.
        time_series: 시간순 정렬된 일별 평균값 목록.
        """
        values = [p["avg"] for p in time_series if p.get("avg") is not None]
        n = len(values)

        if n < self.MIN_DATA_POINTS:
            return {
                "metric": metric_name,
                "confidence": "insufficient_data",
                "message": f"최소 {self.MIN_DATA_POINTS}일 데이터가 필요합니다. 현재: {n}일",
                "predictions": {},
            }

        # 이상치 제거 (IQR 기반)
        cleaned = self._remove_outliers(values)

        # 선형 회귀로 일별 증가율 계산
        slope, intercept = self._linear_regression(cleaned)
        current_value = cleaned[-1]
        trend = "increasing" if slope > 0.1 else ("decreasing" if slope < -0.1 else "stable")

        # 예측
        predictions = {}
        for days in [7, 30, 90]:
            if days <= horizon_days:
                predicted = current_value + slope * days
                predictions[f"{days}d"] = round(min(max(predicted, 0), 100), 2)

        # 고갈 시점 예측 (100% 도달)
        days_to_full = None
        if slope > 0 and current_value < 100:
            days_to_full = int((100 - current_value) / slope)

        # 90% 임계 도달 시점 (warning 기준)
        days_to_warning = None
        if slope > 0 and current_value < 90:
            days_to_warning = int((90 - current_value) / slope)

        # 신뢰도 평가
        std_dev = statistics.stdev(cleaned) if len(cleaned) > 1 else 0
        confidence = "high" if std_dev < 5 else ("medium" if std_dev < 15 else "low")

        return {
            "metric": metric_name,
            "current_value": round(current_value, 2),
            "trend": trend,
            "trend_rate_per_day": round(slope, 4),
            "trend_rate_label": f"{slope:+.2f}%/day",
            "confidence": confidence,
            "std_dev": round(std_dev, 2),
            "data_points": n,
            "predictions": predictions,
            "days_to_90_percent": days_to_warning,
            "days_to_full": days_to_full,
            "predicted_full_date": (
                (datetime.now(timezone.utc) + timedelta(days=days_to_full)).strftime("%Y-%m-%d")
                if days_to_full and days_to_full < 3650
                else None
            ),
        }

    def generate_recommendations(
        self, predictions: list[dict], cluster_name: str
    ) -> list[dict]:
        """예측 결과 기반 권고 사항을 생성한다."""
        recommendations = []

        for pred in predictions:
            if pred.get("confidence") == "insufficient_data":
                continue

            node = pred.get("node_name")
            metric = pred.get("metric")
            days_to_warn = pred.get("days_to_90_percent")
            days_to_full = pred.get("days_to_full")
            current = pred.get("current_value", 0)

            # 즉각 확장 권고 (30일 내 90% 초과 예상)
            if days_to_warn and days_to_warn <= 30:
                urgency = "immediate" if days_to_warn <= 7 else "high"
                recommendations.append({
                    "type": "capacity_expansion",
                    "urgency": urgency,
                    "cluster": cluster_name,
                    "node": node,
                    "resource": metric,
                    "days_until_warning": days_to_warn,
                    "predicted_full_date": pred.get("predicted_full_date"),
                    "recommendation": self._expansion_message(metric, node, days_to_warn, days_to_full),
                    "actions": self._expansion_actions(metric),
                })

            # 과소 사용 최적화 권고 (평균 < 15%)
            if current < 15 and pred.get("trend") in ("stable", "decreasing"):
                recommendations.append({
                    "type": "optimization",
                    "urgency": "low",
                    "cluster": cluster_name,
                    "node": node,
                    "resource": metric,
                    "avg_usage": current,
                    "recommendation": f"{node}의 {metric}이 {current}%로 지속적으로 낮습니다. 워크로드 통합 또는 노드 축소를 검토하세요.",
                    "potential_saving": "해당 리소스 통합 시 약 20~30% 인프라 비용 절감 가능",
                })

        # 우선순위 정렬 (immediate > high > low)
        urgency_order = {"immediate": 0, "high": 1, "medium": 2, "low": 3}
        recommendations.sort(key=lambda r: urgency_order.get(r.get("urgency", "low"), 99))
        return recommendations

    def _expansion_message(self, metric, node, days_to_warn, days_to_full) -> str:
        resource_names = {
            "disk_usage_ratio": "디스크",
            "memory_usage_ratio": "메모리",
            "cpu_usage_ratio": "CPU",
        }
        res = resource_names.get(metric, metric)
        msg = f"{node}의 {res}이 {days_to_warn}일 내 경고 수준(90%)에 도달 예상."
        if days_to_full:
            msg += f" 약 {days_to_full}일 내 고갈 예상."
        return msg

    def _expansion_actions(self, metric) -> list[str]:
        actions = {
            "disk_usage_ratio": [
                "LVM 확장: lvextend -L +200G /dev/vg0/data && resize2fs /dev/vg0/data",
                "불필요한 로그 정리: journalctl --vacuum-size=2G",
                "Docker 이미지 정리: docker image prune -a --filter 'until=168h'",
            ],
            "memory_usage_ratio": [
                "노드 메모리 증설 또는 신규 노드 추가",
                "파드 memory limit 최적화 및 VPA 적용 검토",
                "메모리 집중 워크로드를 고사양 노드로 이전",
            ],
            "cpu_usage_ratio": [
                "노드 CPU 업그레이드 또는 신규 노드 추가",
                "HPA 설정으로 수평 스케일링 자동화",
                "CPU 집중 작업 오프피크 시간대로 스케줄링",
            ],
        }
        return actions.get(metric, ["해당 리소스 증설 또는 워크로드 최적화 검토"])

    def _linear_regression(self, values: list[float]) -> tuple[float, float]:
        """최소제곱법으로 기울기와 절편을 계산한다."""
        n = len(values)
        x = list(range(n))
        x_mean = sum(x) / n
        y_mean = sum(values) / n

        numerator = sum((x[i] - x_mean) * (values[i] - y_mean) for i in range(n))
        denominator = sum((x[i] - x_mean) ** 2 for i in range(n))

        slope = numerator / denominator if denominator != 0 else 0
        intercept = y_mean - slope * x_mean
        return slope, intercept

    def _remove_outliers(self, values: list[float]) -> list[float]:
        """IQR 기반 이상치를 제거한다."""
        if len(values) < 4:
            return values
        sorted_vals = sorted(values)
        q1 = sorted_vals[len(sorted_vals) // 4]
        q3 = sorted_vals[3 * len(sorted_vals) // 4]
        iqr = q3 - q1
        lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        cleaned = [v for v in values if lower <= v <= upper]
        return cleaned if len(cleaned) >= self.MIN_DATA_POINTS else values
```

## 배치 예측 패턴

```python
async def predict_cluster(db, cluster_name: str, horizon_days: int = 30) -> dict:
    """클러스터 전체 노드의 주요 메트릭을 예측한다."""
    predictor = TrendPredictor()
    nodes = await db.query_cluster_nodes(cluster_name)
    all_predictions = []

    for node in nodes:
        node_name = node["node_name"]
        for metric in ["cpu_usage_ratio", "memory_usage_ratio", "disk_usage_ratio"]:
            series = await db.query_metric_timeseries(
                cluster_name, node_name, metric,
                start=(datetime.now(timezone.utc) - timedelta(days=60)).isoformat(),
                end=datetime.now(timezone.utc).isoformat(),
                interval="1d"
            )
            pred = predictor.predict_metric(series, horizon_days, metric)
            pred["node_name"] = node_name
            pred["cluster_name"] = cluster_name
            all_predictions.append(pred)

    recommendations = predictor.generate_recommendations(all_predictions, cluster_name)

    return {
        "predicted_at": datetime.now(timezone.utc).isoformat(),
        "cluster_name": cluster_name,
        "horizon_days": horizon_days,
        "predictions": all_predictions,
        "recommendations": recommendations,
    }
```

## 의존성

```
# 표준 라이브러리(statistics)만 사용 — numpy/scipy 불필요
# 정밀도가 더 필요한 경우: scikit-learn LinearRegression 사용 가능
```
