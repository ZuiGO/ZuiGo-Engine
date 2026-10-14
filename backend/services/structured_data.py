"""JSON-LD structured-data validation for rich-result types (FAQ schema intentionally excluded -
Google deprecated FAQ rich results in May 2026)."""

import json
import re
from datetime import datetime

from backend.db.mongo import get_db

SUPPORTED_TYPES = {
    "Product": ["name", "offers"],
    "Article": ["headline", "author"],
    "Organization": ["name"],
    "BreadcrumbList": ["itemListElement"],
}

def _flatten_ld(data) -> list[dict]:
    """Top-level JSON-LD nodes, with ``@graph`` members promoted to nodes."""
    out: list[dict] = []
    if isinstance(data, list):
        for item in data:
            out.extend(_flatten_ld(item))
    elif isinstance(data, dict):
        graph = data.get("@graph")
        if isinstance(graph, (list, dict)):
            out.extend(_flatten_ld(graph))
        if data.get("@type") or not graph:
            out.append(data)
    return out


def _soup(html: str):
    from bs4 import BeautifulSoup

    return BeautifulSoup(html or "", "lxml")


def detect_structured_data(html_or_soup) -> dict:
    """Detect JSON-LD, Microdata and RDFa. JSON-LD is parsed, not regex-matched.

    Returns {"formats": [...], "nodes": [JSON-LD node dicts], "jsonld_valid": int,
    "jsonld_invalid": int, "types": [type names]} - everything measured from the markup.
    """
    soup = html_or_soup if hasattr(html_or_soup, "find_all") else _soup(html_or_soup)
    formats: list[str] = []
    nodes: list[dict] = []
    valid = invalid = 0
    for tag in soup.find_all("script", attrs={"type": re.compile(r"^application/ld\+json$", re.I)}):
        raw = (tag.string or tag.get_text() or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            invalid += 1
            continue
        found = _flatten_ld(data)
        if found:
            valid += 1
            nodes.extend(found)
    types: list[str] = []
    for node in nodes:
        for t in _type_names(node):
            if t not in types:
                types.append(t)
    if valid:
        formats.append("json-ld")
    micro = [el.get("itemtype") for el in soup.find_all(attrs={"itemscope": True, "itemtype": True})]
    if micro:
        formats.append("microdata")
        for it in micro:
            name = (it or "").rstrip("/").rsplit("/", 1)[-1]
            if name and name not in types:
                types.append(name)
    rdfa = [el.get("typeof") for el in soup.find_all(attrs={"typeof": True})]
    if rdfa:
        formats.append("rdfa")
        for tv in rdfa:
            for name in (tv or "").split():
                name = name.split(":")[-1]
                if name and name not in types:
                    types.append(name)
    return {"formats": formats, "nodes": nodes, "jsonld_valid": valid, "jsonld_invalid": invalid, "types": types}


def _json_ld_objects(html: str) -> list[dict]:
    """JSON-LD nodes of a document (kept for callers/tests of the old helper)."""
    return detect_structured_data(html)["nodes"]


def _type_names(node: dict) -> list[str]:
    t = node.get("@type")
    if isinstance(t, list):
        return [x for x in t if isinstance(x, str)]
    return [t] if isinstance(t, str) else []


def _has_required(obj: dict, type_name: str) -> list[str]:
    required = SUPPORTED_TYPES.get(type_name, [])
    return [f for f in required if f not in obj]


def validate_structured_data(page_url: str, html: str) -> dict:
    report = {
        "page_url": page_url,
        "types_present": [],
        "invalid_types": [],
        "missing_required": {},
        "has_structured_data": False,
        "formats": [],
        "jsonld_parse_errors": 0,
        "valid": False,
    }
    det = detect_structured_data(html)
    report["formats"] = det["formats"]
    report["jsonld_parse_errors"] = det["jsonld_invalid"]
    if not det["formats"]:
        return report
    report["has_structured_data"] = True
    seen = set()
    valid_types = set()
    # Required-field validation only applies to JSON-LD nodes (the only format parsed into fields).
    for obj in det["nodes"]:
        for t in _type_names(obj):
            if t in seen:
                continue
            seen.add(t)
            report["types_present"].append(t)
            if t in SUPPORTED_TYPES:
                missing = _has_required(obj, t)
                if missing:
                    report["invalid_types"].append(t)
                    report["missing_required"][t] = missing
                else:
                    valid_types.add(t)
            elif t in ("FAQPage", "FAQPageQuestion"):
                report["types_present"].append(f"{t} (deprecated - ignored)")
    for t in det["types"]:  # microdata / RDFa types: present, not field-validated
        if t not in report["types_present"] and t not in seen:
            report["types_present"].append(t)
    report["valid"] = bool(valid_types) and not report["invalid_types"]
    return report


async def audit_structured_data(job_id: str) -> dict:
    db = get_db()
    pages = await db.pages.find({"job_id": job_id}, {"html": 1, "url": 1, "status_code": 1}).to_list(length=None)
    pages = [p for p in pages if (p.get("status_code") or 200) < 400]  # error pages have no content to audit
    if not pages:
        return {"status": "error", "message": "No pages for this job"}

    per_page = []
    valid_count = 0
    missing_count = 0
    invalid_count = 0
    type_counts = {}
    for p in pages:
        report = validate_structured_data(p["url"], p.get("html") or "")
        per_page.append(report)
        if report["has_structured_data"]:
            if report["valid"]:
                valid_count += 1
            elif report["invalid_types"]:
                invalid_count += 1
            else:
                missing_count += 1
        for t in report["types_present"]:
            type_counts[t] = type_counts.get(t, 0) + 1

    summary = {
        "job_id": job_id,
        "pages": len(pages),
        "with_structured_data": valid_count + invalid_count + missing_count,
        "valid": valid_count,
        "invalid_types": invalid_count,
        "no_structured_data": len(pages) - valid_count - invalid_count - missing_count,
        "type_counts": type_counts,
        "per_page": per_page,
        "generated_at": datetime.utcnow(),
    }
    await db.structured_data.update_one(
        {"job_id": job_id},
        {"$set": summary},
        upsert=True,
    )
    return summary


async def get_structured_data(job_id: str) -> dict | None:
    db = get_db()
    doc = await db.structured_data.find_one({"job_id": job_id})
    if doc:
        doc["id"] = str(doc.pop("_id"))
    return doc
