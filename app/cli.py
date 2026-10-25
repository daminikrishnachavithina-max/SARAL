"""SARAL command line. Run:  python -m app.cli <command> --help"""
import argparse

from .db import get_connection, init_db
from .eligibility import evaluate, load_criteria, application_state
from .updater import process_source, run_all


def cmd_approve(a):
    from datetime import date,datetime, timezone
    import json

    with get_connection() as conn:
        o = conn.execute(
            "SELECT * FROM opportunities WHERE id = ?", (a.opp,)
        ).fetchone()

        if not o:
            print(f"Opportunity {a.opp} not found.")
            return

        print(f"Opportunity: {o['name']}")
        print(f"Organization: {o['org_name']}")
        print(f"Official source: {o['official_url']}")
        print(f"Current status: {o['verification_status']}")

        if not a.note.strip():
            print("Approval cancelled: provide a verification note.")
            return

        if not o["official_url"].lower().startswith("https://"):
            print("Approval refused: official source must use HTTPS.")
            return
        if (o["application_status"] or "").lower() != "open":
            print("Approval refused: opportunity is not currently open.")
            return

        if o["deadline"]:
            try:
                deadline = date.fromisoformat(o["deadline"])
            except ValueError:
                print("Approval refused: deadline is invalid.")
                return

            if deadline < date.today():
                print("Approval refused: deadline has passed.")
                return

        confirm = input(
            "Have you checked this opportunity on its official source? Type YES to confirm: "
        )
        if confirm != "YES":
            print("Approval cancelled.")
            return

        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE opportunities SET verification_status='verified' WHERE id=?",
            (a.opp,)
        )

        snapshot = dict(o)
        snapshot["verification_status"] = "verified"
        conn.execute(
            """INSERT INTO opportunity_versions
               (opportunity_id, version, snapshot_json, change_summary,
                source_url, retrieved_at, verified_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                a.opp, o["current_version"],
                json.dumps(snapshot, sort_keys=True),
                "Manually verified: " + a.note.strip(),
                o["official_url"], now, now
            )
        )

        print("Opportunity marked verified.")
def cmd_add_source(a):
    with get_connection() as conn:
        conn.execute("INSERT OR IGNORE INTO sources (name, organization, url, source_type, poll_minutes) VALUES (?,?,?,?,?)",
                     (a.name, a.org, a.url, a.type, a.poll))
        row = conn.execute("SELECT id FROM sources WHERE url=?", (a.url,)).fetchone()
    print(f"Source registered with id {row['id']}.")


def cmd_check(a):
    with get_connection() as conn:
        if a.source == "all":
            results = run_all(conn, force=True)
        else:
            results = [process_source(conn, int(a.source))]
    for r in results:
        print(f"Source {r['source_id']}: {r['status']} | created={r['created']} updated={r['updated']} "
              f"unchanged={r['unchanged']} pending={r['pending']} | {r['message']}")


def cmd_show(a):
    with get_connection() as conn:
        print("== SOURCES ==")
        for s in conn.execute("SELECT * FROM sources").fetchall():
            print(f"[{s['id']}] {s['name']} ({s['source_type']}) status={s['last_status']} "
                  f"last_checked={s['last_checked_at']} last_success={s['last_success_at']} failures={s['consecutive_failures']}")
            if s["last_error"]:
                print(f"     note: {s['last_error']}")
        print("\n== OPPORTUNITIES ==")
        for o in conn.execute("SELECT * FROM opportunities").fetchall():
            _, text = application_state(o["deadline"])
            print(f"[{o['id']}] {o['name']} - {o['org_name']}")
            print(f"     version {o['current_version']} | {o['verification_status']} | {text}")
            print(f"     last checked {o['last_checked_at']} | last success {o['last_success_at']}")
            print(f"     official source: {o['official_url']}")
        n = conn.execute("SELECT COUNT(*) FROM pending_changes WHERE status='pending'").fetchone()[0]
        print(f"\nChanges waiting for review: {n}")


def cmd_pending(a):
    with get_connection() as conn:
        for p in conn.execute("SELECT * FROM pending_changes WHERE status='pending'").fetchall():
            print(f"#{p['id']} (opportunity {p['opportunity_id']}, source {p['source_id']}) {p['created_at']}\n   {p['reason']}")


def cmd_history(a):
    with get_connection() as conn:
        for v in conn.execute("SELECT * FROM opportunity_versions WHERE opportunity_id=? ORDER BY version", (a.opp,)).fetchall():
            print(f"v{v['version']} retrieved {v['retrieved_at']} from {v['source_url']}\n   {v['change_summary']}")



def cmd_match(a):
    profile = {}

    if a.level:
        profile["education_level"] = a.level
    if a.income is not None:
        profile["income"] = a.income
    if a.marks is not None:
        profile["marks_percent"] = a.marks

    with get_connection() as conn:
        opportunities = conn.execute(
            "SELECT * FROM opportunities"
        ).fetchall()

        if not opportunities:
            print("No opportunities are currently recorded in SARAL.")
            print("Add and verify genuine opportunities before matching applicants.")
            return

        for o in opportunities:
            res = evaluate(load_criteria(conn, o["id"]), profile)

            print(
                f"\n{o['name']} ({o['org_name']}), "
                f"rules version {o['current_version']}"
            )
            print(f"  RESULT: {res['overall_text']}")

            for c in res["criteria"]:
                print(f"   - [{c['status']}] {c['label']}: {c['reason']}")

            print(f"  Official source: {o['official_url']}")
            print(f"  {res['note']}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init").set_defaults(fn=lambda a: (init_db(), print("Database ready.")))
    s = sub.add_parser("add-source")
    s.add_argument("--name", required=True); s.add_argument("--org", required=True)
    s.add_argument("--url", required=True); s.add_argument("--type", default="api")
    s.add_argument("--poll", type=int, default=360, help="minutes between checks")
    s.set_defaults(fn=cmd_add_source)
    c = sub.add_parser("check"); c.add_argument("source", help="a source id, or 'all'"); c.set_defaults(fn=cmd_check)
    sub.add_parser("show").set_defaults(fn=cmd_show)
    sub.add_parser("pending").set_defaults(fn=cmd_pending)
    h = sub.add_parser("history"); h.add_argument("opp", type=int); h.set_defaults(fn=cmd_history)
    ap = sub.add_parser("approve")
    ap.add_argument("opp", type=int, help="opportunity ID")
    ap.add_argument("--note", required=True, help="what you checked on the official source")
    ap.set_defaults(fn=cmd_approve)
    m = sub.add_parser("match")
    m.add_argument("--level");
    m.add_argument("--income", type=float);
    m.add_argument("--marks", type=float)
    m.set_defaults(fn=cmd_match)
    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
