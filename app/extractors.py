"""SARAL extractors: turn raw source content into structured records.

An extractor never guesses. If the content does not look as expected
(layout changed, bad format, nothing found) it raises ExtractionError
and the source is flagged for review.
"""
import json


class ExtractionError(Exception):
    pass


def _s(v):
    if v is None:
        return None
    v = str(v).strip()
    return v or None


def extract_records(source_type, content):
    if source_type == "api":
        return _extract_json_feed(content)
    raise ExtractionError(
        f"No extractor is set up for source type '{source_type}' yet, so this source needs review.")


def _extract_json_feed(content):
    try:
        data = json.loads(content.lstrip("\ufeff"))
    except ValueError:
        raise ExtractionError("The source did not return valid JSON (its format may have changed).")
    items = data.get("opportunities") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        raise ExtractionError("No opportunities found in the feed (its format may have changed).")
    records = []
    for item in items:
        if not isinstance(item, dict):
            raise ExtractionError("An entry in the feed was not in the expected format.")
        records.append({
            "name": _s(item.get("name")),
            "org_name": _s(item.get("org_name")),
            "description": _s(item.get("description")),
            "category": _s(item.get("category")) or "education",
            "state": _s(item.get("state")),
            "official_url": _s(item.get("official_url")),
            "apply_url": _s(item.get("apply_url")),
            "deadline": _s(item.get("deadline")),
            "application_status": (_s(item.get("application_status")) or "unknown").lower(),
            "funding": _s(item.get("funding")),
            "published_at": _s(item.get("published_at")),
            "documents": item.get("documents", []),   # checked by the validator
            "criteria": item.get("criteria", []),     # checked by the validator
        })
    return records
