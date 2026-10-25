"""Reproducible test: official source changes -> SARAL detects, validates,
updates, and uses the NEW rule in the next eligibility check.
Uses a fake in-memory 'official source'. It does NOT contact any real website."""
import json
import sqlite3

from app.db import SCHEMA
from app.collector import FetchResult
from app.eligibility import evaluate, load_criteria, POTENTIALLY_ELIGIBLE, LIKELY_NOT_ELIGIBLE
from app.updater import process_source

URL = "https://scholarships.example.org/feed.json"


def make_feed(deadline="2026-12-31", income_limit=250000, apply_url="https://scholarships.example.org/apply"):
    return json.dumps({"opportunities": [{
        "name": "Sample Merit Scholarship",
        "org_name": "Sample Education Trust",
        "description": "Sample scheme used only for testing.",
        "official_url": "https://scholarships.example.org/merit",
        "apply_url": apply_url,
        "deadline": deadline,
        "application_status": "open",
        "documents": ["Marksheet", "Income certificate"],
        "criteria": [
            {"field": "education_level", "operator": "in", "value": ["undergraduate"], "label": "Studying at undergraduate level"},
            {"field": "income", "operator": "lte", "value": income_limit, "label": f"Family income up to Rs {income_limit} per year"},
        ],
    }]})


def fake_fetch(content, status="ok", error=""):
    def _fetch(url):
        return FetchResult(status, 200 if status == "ok" else None, content, "application/json", error, "2026-10-24T10:00:00+00:00")
    return _fetch


def new_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO sources (name, organization, url, source_type, active) VALUES (?,?,?,?,1)",
                 ("Sample feed", "Sample Education Trust", URL, "api"))
    conn.commit()
    return conn


def opp(conn):
    return dict(conn.execute("SELECT * FROM opportunities").fetchone())


CITIZEN = {"education_level": "undergraduate", "income": 200000}


def test_first_check_creates_verified_record():
    conn = new_db()
    r = process_source(conn, 1, fetch_fn=fake_fetch(make_feed()))
    o = opp(conn)
    assert r["created"] == 1 and o["verification_status"] == "unverified"
    assert o["current_version"] == 1 and o["last_success_at"] and o["deadline"] == "2026-12-31"


def test_changed_deadline_and_rule_are_detected_validated_and_used():
    conn = new_db()
    process_source(conn, 1, fetch_fn=fake_fetch(make_feed()))
    # Before the change: income 200000 is within the 250000 limit.
    before = evaluate(load_criteria(conn, 1), CITIZEN)
    assert before["overall"] == POTENTIALLY_ELIGIBLE

    # The official source now publishes a new deadline AND a lower income limit.
    r = process_source(conn, 1, fetch_fn=fake_fetch(make_feed(deadline="2027-01-15", income_limit=150000)))

    assert r["updated"] == 1 and r["pending"] == 0           # detected + validated
    o = opp(conn)
    assert o["deadline"] == "2027-01-15" and o["current_version"] == 2   # record updated
    versions = conn.execute("SELECT version, change_summary FROM opportunity_versions ORDER BY version").fetchall()
    assert [v["version"] for v in versions] == [1, 2]        # history kept
    assert "deadline" in versions[1]["change_summary"] and "150000" in versions[1]["change_summary"]

    after = evaluate(load_criteria(conn, 1), CITIZEN)        # same citizen, new rule
    assert after["overall"] == LIKELY_NOT_ELIGIBLE
    # old rule rows are still stored as history
    assert conn.execute("SELECT COUNT(*) FROM criteria WHERE version=1").fetchone()[0] == 2


def test_unchanged_page_is_not_reprocessed():
    conn = new_db()
    process_source(conn, 1, fetch_fn=fake_fetch(make_feed()))
    r = process_source(conn, 1, fetch_fn=fake_fetch(make_feed()))
    assert r["message"] == "No change." and opp(conn)["current_version"] == 1


def test_invalid_change_is_not_applied():
    conn = new_db()
    process_source(conn, 1, fetch_fn=fake_fetch(make_feed()))
    r = process_source(conn, 1, fetch_fn=fake_fetch(make_feed(deadline="31/12/2026")))
    o = opp(conn)
    assert r["pending"] == 1 and r["status"] == "needs_review"
    assert o["deadline"] == "2026-12-31" and o["current_version"] == 1     # old verified data kept
    assert o["verification_status"] == "needs_review"
    assert conn.execute("SELECT COUNT(*) FROM pending_changes").fetchone()[0] == 1
    process_source(conn, 1, fetch_fn=fake_fetch(make_feed(deadline="31/12/2026")))
    assert conn.execute("SELECT COUNT(*) FROM pending_changes").fetchone()[0] == 1   # no duplicates


def test_link_to_another_website_is_rejected():
    conn = new_db()
    process_source(conn, 1, fetch_fn=fake_fetch(make_feed()))
    bad = json.loads(make_feed())
    bad["opportunities"][0]["official_url"] = "https://evil.example.net/merit"
    r = process_source(conn, 1, fetch_fn=fake_fetch(json.dumps(bad)))
    assert r["pending"] == 1 and opp(conn)["official_url"] == "https://scholarships.example.org/merit"


def test_failed_fetch_keeps_old_data_and_is_logged():
    conn = new_db()
    process_source(conn, 1, fetch_fn=fake_fetch(make_feed()))
    r = process_source(conn, 1, fetch_fn=fake_fetch("", "error", "Server error 503"))
    s = dict(conn.execute("SELECT * FROM sources").fetchone())
    assert r["status"] == "error" and s["consecutive_failures"] == 1 and s["last_status"] == "error"
    assert opp(conn)["deadline"] == "2026-12-31"
    assert conn.execute("SELECT COUNT(*) FROM fetch_log WHERE outcome='error'").fetchone()[0] == 1


def test_crashing_fetch_does_not_crash_saral():
    conn = new_db()
    def boom(url):
        raise RuntimeError("network exploded")
    assert process_source(conn, 1, fetch_fn=boom)["status"] == "error"


def test_repeated_failures_flag_source_for_review():
    conn = new_db()
    for _ in range(3):
        process_source(conn, 1, fetch_fn=fake_fetch("", "error", "down"))
    assert conn.execute("SELECT last_status FROM sources").fetchone()[0] == "needs_review"


def test_broken_layout_is_flagged_not_guessed():
    conn = new_db()
    process_source(conn, 1, fetch_fn=fake_fetch(make_feed()))
    r = process_source(conn, 1, fetch_fn=fake_fetch("<html>We redesigned our site!</html>"))
    assert r["status"] == "needs_review" and opp(conn)["current_version"] == 1


def test_opportunity_removed_from_source_is_flagged_not_deleted():
    conn = new_db()
    process_source(conn, 1, fetch_fn=fake_fetch(make_feed()))
    other = json.loads(make_feed())
    other["opportunities"][0]["name"] = "A Different Scholarship"
    process_source(conn, 1, fetch_fn=fake_fetch(json.dumps(other)))
    rows = conn.execute("SELECT name, verification_status FROM opportunities ORDER BY id").fetchall()
    assert rows[0]["name"] == "Sample Merit Scholarship" and rows[0]["verification_status"] == "needs_review"
