"""CrisisCatalog 유닛 테스트."""
import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../src'))

from analysis.crisis_catalog import CRISIS_CATALOG

EXPECTED_TYPES = [
    "HIGH_CPU",
    "MEMORY_EXHAUSTION",
    "DISK_FULL",
    "HIGH_LOAD",
    "CRASHLOOP_BACKOFF",
    "NODE_NOT_READY",
    "OOM_KILLED",
]


def test_all_types_present():
    for t in EXPECTED_TYPES:
        assert t in CRISIS_CATALOG, f"{t} 누락"


def test_each_type_has_required_fields():
    for t, info in CRISIS_CATALOG.items():
        assert "description"      in info, f"{t}.description 누락"
        assert "diagnosis_steps"  in info, f"{t}.diagnosis_steps 누락"
        assert "immediate_actions" in info, f"{t}.immediate_actions 누락"
        assert "references"       in info, f"{t}.references 누락"


def test_references_have_url():
    for t, info in CRISIS_CATALOG.items():
        for ref in info.get("references", []):
            assert "url"   in ref, f"{t} reference에 url 없음"
            assert "title" in ref, f"{t} reference에 title 없음"


def test_immediate_actions_are_strings():
    for t, info in CRISIS_CATALOG.items():
        for action in info.get("immediate_actions", []):
            assert isinstance(action, str), f"{t} action이 문자열이 아님"
