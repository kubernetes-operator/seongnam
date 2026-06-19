"""시계열 메트릭 트렌드 분석 및 미래 상태 예측."""
import statistics
from datetime import datetime, timezone, timedelta
from typing import Optional


class TrendPredictor:
    """일별 평균값 시계열로 미래 리소스 사용량을 예측한다."""

    MIN_DATA_POINTS = 14

    def predict_metric(
        self,
        time_series: list[dict],
        horizon_days: int = 30,
        metric_name: str = "metric",
    ) -> dict:
        # DB 쿼리 결과 키: "avg", "{first_word}_avg" (예: cpu_avg), 또는 전체 컬럼명
        prefix = metric_name.split("_")[0]  # cpu_usage_ratio → cpu
        values = [
            p.get("avg") or p.get(f"{prefix}_avg") or p.get(f"{metric_name}_avg")
            for p in time_series
        ]
        values = [v for v in values if v is not None]
        n = len(values)

        if n < self.MIN_DATA_POINTS:
            return {
                "metric": metric_name,
                "status": "insufficient_data",
                "confidence": "insufficient_data",
                "message": f"최소 {self.MIN_DATA_POINTS}일 데이터가 필요합니다. 현재: {n}일",
                "predictions": {},
            }

        cleaned = self._remove_outliers(values)
        slope, intercept = self._linear_regression(cleaned)
        current = cleaned[-1]
        trend = "increasing" if slope > 0.1 else ("decreasing" if slope < -0.1 else "stable")

        predictions = {}
        for days in [7, 30, 90]:
            if days <= horizon_days:
                predicted = current + slope * days
                predictions[f"{days}d"] = round(min(max(predicted, 0), 100), 2)

        days_to_full = None
        if slope > 0 and current < 100:
            days_to_full = int((100 - current) / slope)

        confidence = "high" if n >= 30 else ("medium" if n >= 14 else "low")
        if abs(slope) < 0.01:
            confidence = "high"

        return {
            "status": "ok",
            "metric": metric_name,
            "current_value": round(current, 2),
            "trend": trend,
            "slope_per_day": round(slope, 4),
            "predictions": predictions,
            "forecast_7d":  predictions.get("7d", round(current + slope * 7,  2)),
            "forecast_30d": predictions.get("30d", round(current + slope * 30, 2)),
            "forecast_90d": predictions.get("90d"),
            "days_to_full": days_to_full,
            "confidence": confidence,
            "data_points": n,
        }

    def generate_recommendations(
        self,
        cluster_name: str,
        node_predictions: list[dict],
    ) -> list[dict]:
        recs = []
        for node_pred in node_predictions:
            node_name = node_pred.get("node_name", "unknown")
            for metric, pred in node_pred.get("predictions", {}).items():
                if not isinstance(pred, dict) or pred.get("confidence") == "insufficient_data":
                    continue

                days_to_full = pred.get("days_to_full")
                current = pred.get("current_value", 0)
                pred_30d = pred.get("predictions", {}).get("30d", 0)

                if days_to_full is not None and days_to_full <= 30:
                    recs.append({
                        "type": "capacity_expansion",
                        "urgency": "high" if days_to_full <= 7 else "medium",
                        "cluster": cluster_name,
                        "node": node_name,
                        "resource": metric,
                        "current_usage_ratio": current,
                        "days_remaining": days_to_full,
                        "recommendation": f"{node_name}의 {metric}이 {days_to_full}일 내 고갈 예상. 용량 확장 필요.",
                    })
                elif current < 10 and pred_30d < 15:
                    recs.append({
                        "type": "optimization",
                        "urgency": "low",
                        "cluster": cluster_name,
                        "node": node_name,
                        "resource": metric,
                        "avg_usage_ratio": current,
                        "recommendation": f"{node_name}의 {metric} 평균 사용률이 {current:.1f}%로 과소 사용 중.",
                    })
        return recs

    def _linear_regression(self, values: list[float]) -> tuple[float, float]:
        n = len(values)
        x_vals = list(range(n))
        x_mean = statistics.mean(x_vals)
        y_mean = statistics.mean(values)
        numerator   = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_vals, values))
        denominator = sum((x - x_mean) ** 2 for x in x_vals)
        slope = numerator / denominator if denominator != 0 else 0.0
        intercept = y_mean - slope * x_mean
        return slope, intercept

    def _remove_outliers(self, values: list[float]) -> list[float]:
        if len(values) < 4:
            return values
        q1 = statistics.quantiles(values, n=4)[0]
        q3 = statistics.quantiles(values, n=4)[2]
        iqr = q3 - q1
        low, high = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        cleaned = [v for v in values if low <= v <= high]
        return cleaned if len(cleaned) >= 4 else values
