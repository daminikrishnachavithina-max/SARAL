from datetime import date
from app.eligibility import (evaluate, evaluate_criterion, application_state,
                             POTENTIALLY_ELIGIBLE, MORE_INFO_NEEDED, LIKELY_NOT_ELIGIBLE,
                             MATCHED, NOT_MATCHED, UNKNOWN)

# Sample rules only (NOT a real scheme). Used just to test the engine.
RULES = [
    {"field": "education_level", "operator": "in", "value": ["undergraduate", "postgraduate"], "label": "Studying at degree level"},
    {"field": "income", "operator": "lte", "value": 250000, "label": "Family income up to 2.5 lakh per year"},
    {"field": "marks_percent", "operator": "gte", "value": 60, "label": "At least 60% in last exam"},
]

def test_all_matched():
    p = {"education_level": "Undergraduate", "income": {"min": 100000, "max": 200000}, "marks_percent": 75}
    assert evaluate(RULES, p)["overall"] == POTENTIALLY_ELIGIBLE

def test_one_not_matched_means_likely_not_eligible():
    p = {"education_level": "undergraduate", "income": 400000, "marks_percent": 75}
    r = evaluate(RULES, p)
    assert r["overall"] == LIKELY_NOT_ELIGIBLE
    assert [c["status"] for c in r["criteria"]] == [MATCHED, NOT_MATCHED, MATCHED]

def test_skipped_answer_is_unknown_not_guessed():
    p = {"education_level": "undergraduate", "income": 100000}
    r = evaluate(RULES, p)
    assert r["overall"] == MORE_INFO_NEEDED
    assert r["criteria"][2]["status"] == UNKNOWN

def test_income_band_crossing_limit_is_unknown():
    c = RULES[1]
    assert evaluate_criterion(c, {"income": {"min": 200000, "max": 300000}})["status"] == UNKNOWN

def test_not_matched_beats_unknown():
    p = {"education_level": "school", "income": 100000}
    assert evaluate(RULES, p)["overall"] == LIKELY_NOT_ELIGIBLE

def test_no_criteria_never_says_eligible():
    assert evaluate([], {"income": 1})["overall"] == MORE_INFO_NEEDED

def test_expired_is_not_shown_open():
    assert application_state("2025-01-01", today=date(2026, 10, 24))[0] == "closed"
    assert application_state("2026-12-31", today=date(2026, 10, 24))[0] == "open"
    assert application_state(None)[0] == "unknown"
    assert application_state("not-a-date")[0] == "unknown"
