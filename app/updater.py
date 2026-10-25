"""SARAL updater: detects changes, validates them, and updates the database.

Flow for one source:
  fetch -> (unchanged page? stop) -> extract -> validate -> compare -> save new version
Anything that fails validation goes to pending_changes and the old verified
data stays in place. Nothing here ever raises an error to the caller.
"""
import json
import time
from datetime import datetime, timezone, timedelta

from .collector import fetch_url, content_hash, now_iso
from .extractors import extract_records, ExtractionError
from .validator import validate

TRACKED = ["official_url", "apply_url", "deadline", "application_status",
           "funding", "description", "documents", "state"]
OPP_COLUMNS = ["org_name", "category", "state", "description", "official_url", "apply_url",
               "deadline", "application_status", "funding", "published_at"]
MAX_FAILURES_BEFORE_REVIEW = 3


# ---------- small helpers ----------
def _canon_value(v):
    return sorted(v, key=str) if isinstance(v, list) else v


def _canon_criteria(criteria):
    return {(c["field"], c["operator"]): (_canon_value(c["value"]), c["label"]) for c in criteria}


def _log(conn, source_id, outcome, http_status, message, when):
    conn.execute("INSERT INTO fetch_log (source_id, checked_at, outcome, http_status, message) VALUES (?,?,?,?,?)",
                 (source_id, when, outcome, http_status, (message or "")[:500]))


def _update_source(conn, source_id, **fields):
    cols = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE sources SET {cols} WHERE id = ?", (*fields.values(), source_id))


def _add_pending(conn, opp_id, source_id, proposed, reason, when):
    pj = json.dumps(proposed, sort_keys=True, default=str)
    dup = conn.execute(
        "SELECT 1 FROM pending_changes WHERE source_id=? AND status='pending' AND reason=? "
        "AND proposed_json=? AND IFNULL(opportunity_id,0)=IFNULL(?,0)",
        (source_id, reason, pj, opp_id)).fetchone()
    if not dup:
        conn.execute("INSERT INTO pending_changes (opportunity_id, source_id, proposed_json, reason, created_at) "
                     "VALUES (?,?,?,?,?)", (opp_id, source_id, pj, reason, when))


def _load_current(conn, source_id, name):
    row = conn.execute("SELECT * FROM opportunities WHERE source_id=? AND name=?", (source_id, name)).fetchone()
    if not row:
        return None
    cur = dict(row)
    cur["documents"] = json.loads(cur["documents_json"] or "[]")
    crows = conn.execute("SELECT field, operator, value, label FROM criteria WHERE opportunity_id=? AND version=?",
                         (cur["id"], cur["current_version"])).fetchall()
    cur["criteria"] = [{"field": r["field"], "operator": r["operator"],
                        "value": json.loads(r["value"]), "label": r["label"]} for r in crows]
    return cur


def _diff(current, proposed):
    """List the important differences in plain words."""
    changes = []
    for f in TRACKED:
        old, new = current.get(f), proposed.get(f)
        if f == "documents":
            old, new = sorted(old or []), sorted(new or [])
        if (old or None) != (new or None):
            changes.append(f"{f}: {old!r} -> {new!r}")
    oc, nc = _canon_criteria(current["criteria"]), _canon_criteria(proposed["criteria"])
    for key in sorted(set(oc) | set(nc)):
        if key not in oc:
            changes.append(f"new rule: {nc[key][1]}")
        elif key not in nc:
            changes.append(f"rule removed: {oc[key][1]}")
        elif oc[key][0] != nc[key][0]:
            changes.append(f"rule changed: {oc[key][1]} (value {oc[key][0]!r} -> {nc[key][0]!r})")
        elif oc[key][1] != nc[key][1]:
            changes.append(f"rule wording changed: {oc[key][1]!r} -> {nc[key][1]!r}")
    return changes


def _insert_criteria(conn, opp_id, criteria, version):
    for c in criteria:
        conn.execute("INSERT INTO criteria (opportunity_id, field, operator, value, label, version) VALUES (?,?,?,?,?,?)",
                     (opp_id, c["field"], c["operator"], json.dumps(c["value"]), c["label"], version))


def _insert_version(conn, opp_id, version, rec, summary, source_url, retrieved_at, verified_at):
    snap = {k: rec.get(k) for k in OPP_COLUMNS + ["name", "documents", "criteria"]}
    conn.execute("INSERT INTO opportunity_versions (opportunity_id, version, snapshot_json, change_summary, "
                 "source_url, retrieved_at, verified_at) VALUES (?,?,?,?,?,?,?)",
                 (opp_id, version, json.dumps(snap, sort_keys=True), summary, source_url, retrieved_at, verified_at))


def _create(conn, source_id, rec, source_url, fetched_at, now):
    cols = ["source_id", "name", "documents_json", "verification_status",
            "last_checked_at", "last_success_at", "current_version"] + OPP_COLUMNS
    vals = [source_id, rec["name"], json.dumps(rec["documents"]), "unverified", now, now, 1] + [rec.get(c) for c in OPP_COLUMNS]
    cur = conn.execute(f"INSERT INTO opportunities ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", vals)
    opp_id = cur.lastrowid
    _insert_criteria(conn, opp_id, rec["criteria"], 1)
    _insert_version(conn, opp_id, 1, rec, "First record retrieved; verification pending.", source_url, fetched_at, None)


def _update(conn, current, rec, summary, source_url, fetched_at, now):
    version = current["current_version"] + 1
    sets = ", ".join(f"{c} = ?" for c in OPP_COLUMNS)
    conn.execute(f"UPDATE opportunities SET {sets}, documents_json=?, "
                     "last_checked_at=?, last_success_at=?, current_version=? WHERE id=?",
                 [rec.get(c) for c in OPP_COLUMNS] + [json.dumps(rec["documents"]), now, now, version, current["id"]])
    _insert_criteria(conn, current["id"], rec["criteria"], version)   # old rows stay as history
    _insert_version(conn, current["id"], version, rec, summary, source_url, fetched_at, None)


# ---------- main entry points ----------
def process_source(conn, source_id, fetch_fn=None, now_fn=None):
    """Check one source. Always returns a summary dict and never raises."""
    fetch_fn = fetch_fn or fetch_url
    now_fn = now_fn or now_iso
    summary = {"source_id": source_id, "status": "error", "created": 0, "updated": 0,
               "unchanged": 0, "pending": 0, "message": ""}
    try:
        return _process(conn, source_id, fetch_fn, now_fn, summary)
    except Exception as exc:   # last-resort safety net
        conn.rollback()
        summary["message"] = f"Unexpected problem: {type(exc).__name__}"
        try:
            _log(conn, source_id, "error", None, summary["message"], now_fn())
            conn.commit()
        except Exception:
            pass
        return summary


def _process(conn, source_id, fetch_fn, now_fn, summary):
    src = conn.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
    if not src:
        summary["message"] = "No such source."
        return summary
    if not src["active"]:
        summary.update(status="skipped", message="Source is switched off.")
        return summary
    now = now_fn()

    # 1. fetch
    try:
        result = fetch_fn(src["url"])
    except Exception as exc:
        from .collector import FetchResult
        result = FetchResult("error", error=f"Fetch failed: {type(exc).__name__}", fetched_at=now)

    if result.status != "ok":
        failures = (src["consecutive_failures"] or 0) + 1
        status = "needs_review" if failures >= MAX_FAILURES_BEFORE_REVIEW else result.status
        _log(conn, source_id, result.status, result.http_status, result.error, now)
        _update_source(conn, source_id, last_checked_at=now, last_status=status,
                       last_error=result.error, consecutive_failures=failures)
        conn.execute("UPDATE opportunities SET last_checked_at=? WHERE source_id=?", (now, source_id))
        conn.commit()
        summary.update(status=status, message=result.error)
        return summary

    # 2. unchanged page? (same fingerprint as the last fully processed one)
    new_hash = content_hash(result.content)
    if new_hash == src["content_hash"] and src["last_status"] == "ok":
        _log(conn, source_id, "unchanged", result.http_status, "Page identical to last check.", now)
        _update_source(conn, source_id, last_checked_at=now, last_success_at=now, consecutive_failures=0)
        conn.execute("UPDATE opportunities SET last_checked_at=?, last_success_at=? WHERE source_id=?",
                     (now, now, source_id))
        conn.commit()
        summary.update(status="ok", message="No change.")
        return summary

    # 3. extract
    try:
        records = extract_records(src["source_type"], result.content)
    except ExtractionError as exc:
        _add_pending(conn, None, source_id, {"content_hash": new_hash}, f"Extraction failed: {exc}", now)
        _log(conn, source_id, "error", result.http_status, f"Extraction failed: {exc}", now)
        _update_source(conn, source_id, last_checked_at=now, last_success_at=now,
                       last_status="needs_review", last_error=str(exc), consecutive_failures=0)
        conn.commit()
        summary.update(status="needs_review", pending=1, message=str(exc))
        return summary

    # 4. validate, compare, apply
    seen_names = set()
    for rec in records:
        name = rec.get("name")
        seen_names.add(name)
        current = _load_current(conn, source_id, name) if name else None
        problems = validate(rec, src["url"], len(current["criteria"]) if current else 0)
        if problems:
            _add_pending(conn, current["id"] if current else None, source_id, rec,
                         "Validation failed: " + " | ".join(problems), now)
            if current:
                conn.execute("UPDATE opportunities SET verification_status='needs_review', last_checked_at=? WHERE id=?",
                             (now, current["id"]))
            summary["pending"] += 1
            continue
        if current is None:
            _create(conn, source_id, rec, src["url"], result.fetched_at, now)
            summary["created"] += 1
            continue
        changes = _diff(current, rec)
        if not changes:
            conn.execute("UPDATE opportunities SET last_checked_at=?, last_success_at=? "
             "WHERE id=?", (now, now, current["id"]))
            summary["unchanged"] += 1
        else:
            _update(conn, current, rec, "; ".join(changes), src["url"], result.fetched_at, now)
            summary["updated"] += 1

    # 5. records that vanished from the source are flagged, never deleted
    for row in conn.execute("SELECT id, name FROM opportunities WHERE source_id=?", (source_id,)).fetchall():
        if row["name"] not in seen_names:
            _add_pending(conn, row["id"], source_id, {"name": row["name"]},
                         "No longer listed on the official source.", now)
            conn.execute("UPDATE opportunities SET verification_status='needs_review', last_checked_at=? WHERE id=?",
                         (now, row["id"]))
            summary["pending"] += 1

    clean = summary["pending"] == 0
    changed = summary["created"] + summary["updated"] > 0
    _log(conn, source_id, "changed" if changed else "ok", result.http_status,
         f"created={summary['created']} updated={summary['updated']} pending={summary['pending']}", now)
    _update_source(conn, source_id, last_checked_at=now, last_success_at=now,
                   last_status="ok" if clean else "needs_review",
                   last_error=None if clean else "Some changes need review.",
                   consecutive_failures=0, content_hash=new_hash if clean else src["content_hash"])
    conn.commit()
    summary["status"] = "ok" if clean else "needs_review"
    summary["message"] = "Checked."
    return summary


def run_all(conn, force=False, fetch_fn=None, delay_seconds=1.0):
    """Check every active source that is due (or all of them if force=True)."""
    out = []
    now = datetime.now(timezone.utc)
    rows = conn.execute("SELECT id, poll_minutes, last_checked_at FROM sources WHERE active=1").fetchall()
    for r in rows:
        due = force or not r["last_checked_at"]
        if not due:
            last = datetime.fromisoformat(r["last_checked_at"])
            due = now - last >= timedelta(minutes=r["poll_minutes"] or 360)
        if due:
            out.append(process_source(conn, r["id"], fetch_fn=fetch_fn))
            time.sleep(delay_seconds)   # be polite between different sources
    return out
