"""SARAL eligibility engine.

Deterministic and rule-based. No AI is used here.
Each criterion is compared to the citizen's answers and gets ONE of:
    matched / not_matched / unknown
The overall label is then worked out from those results:
    any not_matched        -> likely_not_eligible
    else any unknown       -> more_information_needed
    else (all matched)     -> potentially_eligible
SARAL never guarantees eligibility, selection, funding or approval.
"""
import json
from datetime import date

MATCHED = "matched"
NOT_MATCHED = "not_matched"
UNKNOWN = "unknown"

POTENTIALLY_ELIGIBLE = "potentially_eligible"
MORE_INFO_NEEDED = "more_information_needed"
LIKELY_NOT_ELIGIBLE = "likely_not_eligible"

OVERALL_TEXT = {
    POTENTIALLY_ELIGIBLE: "Potentially eligible",
    MORE_INFO_NEEDED: "More information needed",
    LIKELY_NOT_ELIGIBLE: "Likely not eligible under the listed criteria",
}

SUPPORTED_OPERATORS = ("eq", "in", "lte", "gte")


def _is_blank(v):
    return v is None or v == "" or v == []


def _range_of(v):
    """Turn an answer into (low, high). A plain number is (n, n).
    A band such as {"min": 100000, "max": 250000} is kept as a range."""
    if isinstance(v, dict):
        lo, hi = v.get("min"), v.get("max")
        if lo is None and hi is None:
            return None
        lo = hi if lo is None else lo
        hi = lo if hi is None else hi
        return float(lo), float(hi)
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v), float(v)
    return None


def _norm(v):
    return v.strip().lower() if isinstance(v, str) else v


def evaluate_criterion(criterion, profile):
    """Check one criterion. Returns a dict with status and a plain reason."""
    field = criterion["field"]
    op = criterion["operator"]
    value = criterion["value"]
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            pass
    label = criterion["label"]
    answer = profile.get(field)

    result = {"field": field, "label": label, "status": UNKNOWN, "reason": ""}

    if op not in SUPPORTED_OPERATORS:
        result["reason"] = f"Rule type '{op}' is not supported, so this needs review."
        return result

    if _is_blank(answer):
        result["reason"] = "You did not give this information, so we cannot check it."
        return result

    if op == "eq":
        ok = _norm(answer) == _norm(value)
        result["status"] = MATCHED if ok else NOT_MATCHED
        result["reason"] = (f"Your answer '{answer}' matches the requirement." if ok
                            else f"Your answer '{answer}' does not match the requirement '{value}'.")
        return result

    if op == "in":
        allowed = [_norm(x) for x in value]
        ok = _norm(answer) in allowed
        result["status"] = MATCHED if ok else NOT_MATCHED
        result["reason"] = (f"Your answer '{answer}' is one of the accepted options." if ok
                            else f"Your answer '{answer}' is not among the accepted options: {', '.join(map(str, value))}.")
        return result

    # lte / gte work on numbers or number ranges (e.g. an income band)
    rng = _range_of(answer)
    if rng is None:
        result["reason"] = "Your answer is not a number or range we can compare."
        return result
    lo, hi = rng
    limit = float(value)
    if op == "lte":
        if hi <= limit:
            status, why = MATCHED, f"Your whole range is within the limit of {limit:g}."
        elif lo > limit:
            status, why = NOT_MATCHED, f"Your range is above the limit of {limit:g}."
        else:
            status, why = UNKNOWN, f"Your range crosses the limit of {limit:g}; the exact value is needed."
    else:  # gte
        if lo >= limit:
            status, why = MATCHED, f"Your whole range meets the minimum of {limit:g}."
        elif hi < limit:
            status, why = NOT_MATCHED, f"Your range is below the minimum of {limit:g}."
        else:
            status, why = UNKNOWN, f"Your range crosses the minimum of {limit:g}; the exact value is needed."
    result["status"], result["reason"] = status, why
    return result


def evaluate(criteria, profile):
    """Evaluate all criteria and work out the overall label."""
    results = [evaluate_criterion(c, profile) for c in criteria]
    statuses = [r["status"] for r in results]
    if NOT_MATCHED in statuses:
        overall = LIKELY_NOT_ELIGIBLE
    elif UNKNOWN in statuses or not results:
        # No published criteria also means we cannot say anything firm.
        overall = MORE_INFO_NEEDED
    else:
        overall = POTENTIALLY_ELIGIBLE
    return {
        "overall": overall,
        "overall_text": OVERALL_TEXT[overall],
        "criteria": results,
        "note": "This is guidance based on published criteria, not a guarantee of eligibility or approval.",
    }


def application_state(deadline, today=None):
    """Decide how to describe an opportunity's timing. Never shows an
    expired opportunity as open, and says so when the date is unknown."""
    today = today or date.today()
    if not deadline:
        return "unknown", "Deadline not verified. Check the official site."
    try:
        d = date.fromisoformat(deadline)
    except ValueError:
        return "unknown", "Deadline could not be read. Check the official site."
    if d < today:
        return "closed", f"Closed. Deadline was {deadline}."
    return "open", f"Open until {deadline} (as last verified)."


def load_criteria(conn, opportunity_id):
    """Load criteria for the opportunity's current rules version."""
    rows = conn.execute(
        """SELECT c.field, c.operator, c.value, c.label
           FROM criteria c
           JOIN opportunities o ON o.id = c.opportunity_id
           WHERE c.opportunity_id = ?
             AND c.version = o.current_version
             AND c.id = (
                 SELECT MAX(c2.id)
                 FROM criteria c2
                 WHERE c2.opportunity_id = c.opportunity_id
                   AND c2.version = c.version
                   AND c2.field = c.field
             )
           ORDER BY c.id""",
        (opportunity_id,),
    ).fetchall()
    return [dict(r) for r in rows]
