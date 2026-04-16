from __future__ import annotations

import re


# Canonical Opportunity ID format for this project: "oid" + digits (e.g. "oid1234").
# We still accept a few historical variants in parsing (e.g. "OID_1234", "opp_id_1234")
# but normalize to the canonical form everywhere we store/use it.
_OPP_ID_PATTERN = re.compile(r"(?i)\b(?:oid|opp[_-]?id)[_-]?(\d+)\b")
# e.g. "oid 1112" in body or subject (space between token and digits)
_LOOSE_OID_SPACE_PATTERN = re.compile(r"(?i)\boid\s+(\d+)\b")
# e.g. "opportunity id 200", "opp id: 200", "opportunity-200"
_OPPORTUNITY_PHRASE_PATTERN = re.compile(
    r"(?i)\b(?:opportunity|opp)(?:\s*[_-]?\s*id)?\s*[:#\-_]?\s*(\d+)\b"
)


def normalize_opportunity_oid(value: str) -> str:
    """Normalize an opportunity identifier to canonical form: ``oid<digits>``.

    Accepts case-insensitive inputs like:
      - oid1234, OID1234, oid_1234, oid-1234
      - opp_id_1234, OPP-ID-1234, oppid1234

    Returns:
      Canonical id string like ``oid1234``.

    Raises:
      ValueError if no valid token is found.
    """
    s = (value or "").strip()
    if not s:
        raise ValueError("opportunity oid is required")
    m = _OPP_ID_PATTERN.search(s)
    if m:
        return f"oid{m.group(1)}"
    m2 = _LOOSE_OID_SPACE_PATTERN.search(s)
    if m2:
        return f"oid{m2.group(1)}"
    m3 = _OPPORTUNITY_PHRASE_PATTERN.search(s)
    if m3:
        return f"oid{m3.group(1)}"
    raise ValueError(
        "invalid opportunity oid; expected format like 'oid1234' (oid + digits)"
    )


def find_opportunity_oid(value: str) -> str | None:
    """Extract and normalize an opportunity id from free text; return None if absent."""
    s = (value or "").strip()
    if not s:
        return None
    m = _OPP_ID_PATTERN.search(s)
    if m:
        return f"oid{m.group(1)}"
    m2 = _LOOSE_OID_SPACE_PATTERN.search(s)
    if m2:
        return f"oid{m2.group(1)}"
    m3 = _OPPORTUNITY_PHRASE_PATTERN.search(s)
    if m3:
        return f"oid{m3.group(1)}"
    return None


def gcs_opportunity_prefix(opportunity_id_str: str) -> str:
    """Folder prefix for GCS ``{opportunity_id}/raw/...``.

    Uses canonical ``oid<digits>`` when the string matches the project pattern; otherwise
    returns the stripped DB value (e.g. Salesforce 18-char ids).
    """
    try:
        return normalize_opportunity_oid(opportunity_id_str)
    except ValueError:
        return (opportunity_id_str or "").strip()


def require_stored_opportunity_id(value: str) -> str:
    """Return a non-empty stripped ``opportunities.opportunity_id`` value.

    Use before ORM inserts or raw SQL so we never persist blank strings (Postgres allows
    ``''`` under NOT NULL VARCHAR).
    """
    s = (value or "").strip()
    if not s:
        raise ValueError("opportunity_id is required and cannot be empty")
    return s


def gcs_path_prefix_candidates(db_opportunity_id: str) -> list[str]:
    """Paths to try when reading legacy GCS objects: canonical first, then raw DB id if different."""
    canonical = gcs_opportunity_prefix(db_opportunity_id)
    raw = (db_opportunity_id or "").strip()
    out: list[str] = []
    seen: set[str] = set()
    for x in (canonical, raw):
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out
