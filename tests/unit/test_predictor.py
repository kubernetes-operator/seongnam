"""TrendPredictor 유닛 테스트."""
import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../src'))

from analysis.predictor import TrendPredictor


@pytest.fixture
def predictor():
    return TrendPredictor()


@pytest.fixture
def linear_ts():
    """선형 증가하는 타임시리즈 (14포인트, 50→63%)"""
    return [{"bucket": f"2026-06-{i+1:02d}T00:00:00Z", "cpu_avg": 50.0 + i}
            for i in range(14)]


def test_predict_returns_forecast(predictor, linear_ts):
    result = predictor.predict_metric(linear_ts, metric_name="cpu_usage_ratio")
    assert result["status"] == "ok"
    assert "forecast_7d" in result
    assert "forecast_30d" in result


def test_forecast_increases_for_rising_trend(predictor, linear_ts):
    result = predictor.predict_metric(linear_ts, metric_name="cpu_usage_ratio")
    assert result["forecast_7d"] > result["current_value"]
    assert result["forecast_30d"] > result["forecast_7d"]


def test_days_to_full_calculated(predictor, linear_ts):
    result = predictor.predict_metric(linear_ts, metric_name="cpu_usage_ratio")
    assert result.get("days_to_full") is not None
    assert result["days_to_full"] > 0


def test_insufficient_data(predictor):
    short_ts = [{"bucket": "2026-06-01T00:00:00Z", "cpu_avg": 50.0}]
    result = predictor.predict_metric(short_ts, metric_name="cpu_usage_ratio")
    assert result["status"] == "insufficient_data"


def test_flat_trend_no_days_to_full(predictor):
    flat = [{"bucket": f"2026-06-{i+1:02d}T00:00:00Z", "cpu_avg": 50.0}
            for i in range(14)]
    result = predictor.predict_metric(flat, metric_name="cpu_usage_ratio")
    assert result["days_to_full"] is None


def test_outlier_removal_does_not_crash(predictor):
    ts = [{"bucket": f"2026-06-{i+1:02d}T00:00:00Z", "cpu_avg": 50.0 + (99 if i == 7 else 0)}
          for i in range(14)]
    result = predictor.predict_metric(ts, metric_name="cpu_usage_ratio")
    assert result["status"] in ("ok", "insufficient_data")
