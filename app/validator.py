"""SARAL validator: checks a proposed record BEFORE it can replace verified data.
Returns a list of problems. An empty list means it is safe to apply."""
from datetime import date
from urllib.parse import urlparse

ALLOWED_FIELDS = {
    "country", "state", "education_level", "course", "marks_percent",
    "income", "assistance_type", "category", "gender",
    "age", "employment_status", "occupation", "farmer_status",
    "disability_status", "property_ownership", "house_ownership",
    "vehicle_ownership", "marital_status", "social_category",
    "residency_status", "family_size", "land_ownership",
    "business_ownership", "student_status"
}
ALLOWED_STATUS = {"open", "closed", "upcoming", "unknown"}
OPERATORS = ("eq", "in", "lte", "gte")
LOCAL_HOSTS = {"localhost", "127.0.0.1"}   # allowed over http for local demos only


def _host(url):
    h = (urlparse(url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def _scheme_ok(url):
    p = urlparse(url)
    return p.scheme == "https" or (p.scheme == "http" and (p.hostname or "") in LOCAL_HOSTS)


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def validate(record, source_url, current_criteria_count=0):
    problems = []
    for f in ("name", "org_name", "official_url"):
        if not record.get(f):
            problems.append(f"Required field '{f}' is missing.")

    url = record.get("official_url")
    if url:
        s, h = _host(source_url), _host(url)
        if not _scheme_ok(url):
            problems.append("official_url must use https.")
        if not h or not (h == s or h.endswith("." + s)):
            problems.append("official_url is not on the same website as the registered source.")
    apply_url = record.get("apply_url")
    if apply_url and not _scheme_ok(apply_url):
        problems.append("apply_url must use https.")

    if record.get("deadline"):
        try:
            date.fromisoformat(record["deadline"])
        except ValueError:
            problems.append(f"Deadline '{record['deadline']}' is not a valid YYYY-MM-DD date.")
    if record.get("application_status") not in ALLOWED_STATUS:
        problems.append(f"Application status '{record.get('application_status')}' is not recognised.")

    docs = record.get("documents")
    if not isinstance(docs, list) or not all(isinstance(d, str) for d in docs):
        problems.append("Documents must be a list of text items.")

    criteria = record.get("criteria")
    if not isinstance(criteria, list):
        problems.append("Criteria must be a list.")
        return problems
    if current_criteria_count > 0 and not criteria:
        problems.append("The new version has no eligibility criteria although the verified one had some.")

    seen = set()
    for i, c in enumerate(criteria, 1):
        if not isinstance(c, dict):
            problems.append(f"Criterion {i} is not in the expected format.")
            continue
        field, op, value, label = c.get("field"), c.get("operator"), c.get("value"), c.get("label")
        if field not in ALLOWED_FIELDS:
            problems.append(f"Criterion {i}: unknown field '{field}'.")
        if op not in OPERATORS:
            problems.append(f"Criterion {i}: unsupported operator '{op}'.")
        if not label or not str(label).strip():
            problems.append(f"Criterion {i}: missing plain-words label.")
        if (field, op) in seen:
            problems.append(f"Criterion {i}: duplicate rule for '{field}' '{op}'.")
        seen.add((field, op))
        if op in ("lte", "gte"):
            if not _is_number(value) or value < 0:
                problems.append(f"Criterion {i}: '{op}' needs a number that is zero or more.")
            elif field == "marks_percent" and value > 100:
                problems.append(f"Criterion {i}: marks percentage cannot be above 100.")
            elif field == "income" and value > 100_000_000:
                problems.append(f"Criterion {i}: income limit looks implausible.")
        elif op == "in":
            if not isinstance(value, list) or not value:
                problems.append(f"Criterion {i}: 'in' needs a non-empty list.")
        elif op == "eq":
            if value is None or isinstance(value, (list, dict)):
                problems.append(f"Criterion {i}: 'eq' needs a single value.")
    return problems
