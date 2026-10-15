"""Core Web Vitals via the free Google PageSpeed Insights API (field + lab data).

Fetches mobile CWV for every page and desktop for the homepage, stores per-page results in
`page_performance`, and exposes a job-level summary consumed by site health scoring.
"""

import asyncio
from datetime import datetime

import httpx

from backend.config import settings
from backend.db.mongo import get_db
from backend.logging_setup import get_logger
from backend.services.service_errors import ServiceError
from backend.services.url_normalizer import normalize_url

logger = get_logger("performance")

PSI_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
SERVICE = "pagespeed"
HINT = "Add a Google PageSpeed Insights API key to .env (pagespeed_api_key). Free tier: 100 queries/day by default, extendable to 25k/day."

CWV_METRICS = ("lcp", "inp", "cls")
# Google's published Core Web Vitals thresholds: (good if <=, poor if >).
CWV_THRESHOLDS = {"lcp": (2500, 4000), "inp": (200, 500), "cls": (0.1, 0.25)}
GOOD = {k: v[0] for k, v in CWV_THRESHOLDS.items()}

# PSI v5 field-metric names -> our short names, and Google's own per-metric verdicts.
PSI_FIELD_KEYS = {
    "LARGEST_CONTENTFUL_PAINT_MS": "lcp",
    "INTERACTION_TO_NEXT_PAINT": "inp",
    "CUMULATIVE_LAYOUT_SHIFT_SCORE": "cls",
    "FIRST_CONTENTFUL_PAINT_MS": "fcp",
    "EXPERIMENTAL_TIME_TO_FIRST_BYTE": "ttfb",
}
PSI_CATEGORY = {"FAST": "good", "AVERAGE": "needs-improvement", "SLOW": "poor"}


def classify_metric(name: str, value) -> str | None:
    """good / needs-improvement / poor per Google's thresholds (None if not measured)."""
    if value is None or name not in CWV_THRESHOLDS:
        return None
    good, poor = CWV_THRESHOLDS[name]
    return "good" if value <= good else ("needs-improvement" if value <= poor else "poor")


def _metric_value(lh_audit: dict) -> float | None:
    if not lh_audit:
        return None
    return lh_audit.get("numericValue")


def _parse_experience(exp: dict) -> tuple[dict, dict]:
    """(values, categories) from one PSI loadingExperience block."""
    values, cats = {}, {}
    for key, m in ((exp or {}).get("metrics") or {}).items():
        if not isinstance(m, dict):
            continue
        name = PSI_FIELD_KEYS.get(key, key.lower())  # short names / CrUX-style keys are accepted too
        raw = m.get("percentile")
        if isinstance(raw, dict):  # CrUX-style {"p75": ...}
            raw = raw.get("p75")
            scaled = False
        else:
            scaled = True
        if isinstance(raw, str):
            try:
                raw = float(raw)
            except ValueError:
                raw = None
        if not isinstance(raw, (int, float)):
            continue
        # PSI reports the CLS percentile multiplied by 100 (e.g. 5 means 0.05).
        values[name] = raw / 100.0 if (name == "cls" and scaled) else raw
        cat = PSI_CATEGORY.get(m.get("category"))
        if cat:
            cats[name] = cat
    return values, cats


def _field_experience(data: dict) -> dict:
    """Field (CrUX) data: URL-level metrics, with origin-level data filling metrics the URL lacks."""
    url_vals, url_cats = _parse_experience(data.get("loadingExperience") or {})
    org_vals, org_cats = _parse_experience(data.get("originLoadingExperience") or {})
    values, cats, scopes = dict(url_vals), dict(url_cats), set()
    if url_vals:
        scopes.add("url")
    for k, v in org_vals.items():
        if k not in values:
            values[k] = v
            if k in org_cats:
                cats[k] = org_cats[k]
            scopes.add("origin")
    scope = None if not values else ("mixed" if len(scopes) > 1 else next(iter(scopes)))
    # Google's category is authoritative; flag (do not hide) any disagreement with the value we derived.
    for k in CWV_METRICS:
        if k in values and k in cats and classify_metric(k, values[k]) != cats[k]:
            logger.warning("PSI category %s disagrees with value %s for %s; using Google's category", cats[k], values[k], k)
    return {"values": values, "categories": cats, "scope": scope}


def _field_metrics(data: dict) -> dict:
    return _field_experience(data)["values"]


def _lab_metrics(lr: dict) -> dict:
    audits = lr.get("audits") or {}
    out = {
        "lcp": _metric_value(audits.get("largest-contentful-paint")),
        "inp": _metric_value(audits.get("interaction-to-next-paint")),
        "cls": _metric_value(audits.get("cumulative-layout-shift")),
        "fcp": _metric_value(audits.get("first-contentful-paint")),
        "ttfb": _metric_value(audits.get("server-response-time")),
        "tbt": _metric_value(audits.get("total-blocking-time")),
    }
    # INP is a field-only metric: Lighthouse lab runs do not produce it. Do not substitute
    # another metric (e.g. max-potential-fid) - leave it None and report TBT as the lab proxy.
    return out


def _classify_source(field: dict, cwv: dict) -> str:
    field_keys = set(k for k in CWV_METRICS if field.get(k) is not None)
    missing = set(k for k in CWV_METRICS if cwv.get(k) is None)
    if len(field_keys) == len(CWV_METRICS):
        return "field"
    if field_keys and not missing:
        return "mixed"
    if not field_keys:
        return "lab"
    return "partial"


def _cwv_score(cwv: dict) -> int | None:
    """Percentage of the *measured* core metrics that fall in Google's 'good' range.

    Reproducible from the stored values (no invented weights or partial-credit buckets).
    None when no core metric was measured.
    """
    classes = [classify_metric(k, cwv.get(k)) for k in CWV_METRICS if cwv.get(k) is not None]
    if not classes:
        return None
    return round(100 * sum(1 for c in classes if c == "good") / len(classes))


def cwv_assessment(field: dict, categories: dict | None = None) -> dict:
    """Core Web Vitals assessment from FIELD data only (lab data is diagnostic, not an assessment).

    passed: LCP and CLS measured and good, and INP good where measured.
    failed: any measured metric is not good.
    insufficient-data: otherwise.
    """
    categories = categories or {}
    per = {k: (categories.get(k) or classify_metric(k, field.get(k))) for k in CWV_METRICS}
    measured = {k: v for k, v in per.items() if v}
    if any(v != "good" for v in measured.values()):
        overall = "failed"
    elif "lcp" in measured and "cls" in measured:
        overall = "passed"
    else:
        overall = "insufficient-data"
    return {**per, "overall": overall}


async def fetch_page_performance(url: str, strategy: str = "mobile") -> dict:
    if not settings.pagespeed_api_key:
        raise ServiceError(SERVICE, "PageSpeed Insights API key not configured", hint=HINT)
    params = {
        "url": url,
        "strategy": strategy,
        "category": "performance",
        "key": settings.pagespeed_api_key,
    }
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.get(PSI_URL, params=params)
    except Exception as e:
        raise ServiceError(SERVICE, f"PageSpeed request failed: {e}", hint=HINT) from e
    if resp.status_code >= 400:
        raise ServiceError(
            SERVICE,
            f"PageSpeed ({url}, {strategy}) failed (HTTP {resp.status_code})",
            status_code=resp.status_code,
            hint=HINT,
        )
    data = resp.json()
    try:
        from backend.services.spend_tracker import record_usage
        await record_usage("pagespeed", "", f"psi_{strategy}", requests=1)
    except Exception:
        pass
    exp = _field_experience(data)
    field = exp["values"]
    lab = _lab_metrics(data.get("lighthouseResult") or {})
    cwv = {k: (field.get(k) if field.get(k) is not None else lab.get(k)) for k in CWV_METRICS}
    source = _classify_source(field, cwv)
    return {
        "url": url,
        "strategy": strategy,
        "cwv": cwv,
        "cwv_score": _cwv_score(cwv),
        "cwv_source": source,
        "cwv_assessment": cwv_assessment(field, exp["categories"]),
        "field_scope": exp["scope"],
        "field": field,
        "lab": lab,
        "lighthouse_score": (data.get("lighthouseResult") or {}).get("categories", {}).get("performance", {}).get("score"),
        "fetched_at": datetime.utcnow(),
    }


async def fetch_performance(job_id: str, max_pages: int | None = None) -> dict:
    """Mobile CWV for a sample (cap max_pages or settings.psi_page_sample), desktop for the homepage. Per-page error isolation."""
    db = get_db()
    pages = await db.pages.find({"job_id": job_id}, {"html": 0, "html_mobile": 0}).to_list(length=None)
    if not pages:
        return {"status": "error", "message": "No pages for this job"}

    seen = set()
    deduped = []
    pages = [p for p in pages if (p.get("status_code") or 200) < 400]
    # Home first (it was previously sorted LAST and dropped whenever the sample was smaller than the site),
    # then pages closest to the homepage, then URL for a stable order.
    for p in sorted(pages, key=lambda x: (x.get("page_type") != "home", x.get("click_depth") or 0, x.get("url", ""))):
        norm = normalize_url(p.get("url", ""))
        if not norm:
            continue
        if norm in seen:
            continue
        seen.add(norm)
        p["url"] = norm
        deduped.append(p)
    pages = deduped
    if not pages:
        return {"status": "error", "message": "No crawlable pages for this job"}

    limit = min(len(pages), max_pages if max_pages is not None else settings.psi_page_sample)
    sem = asyncio.Semaphore(settings.psi_concurrency)
    results = []
    errors = []

    async def fetch_one(page: dict):
        async with sem:
            url = page["url"]
            for strategy in (["mobile", "desktop"] if page.get("page_type") == "home" else ["mobile"]):
                try:
                    result = await fetch_page_performance(url, strategy)
                    results.append(result)
                    await db.page_performance.update_one(
                        {"job_id": job_id, "url": url, "strategy": strategy},
                        {"$set": {"job_id": job_id, **result}},
                        upsert=True,
                    )
                except Exception as e:
                    errors.append(f"{url} ({strategy}): {e}")

    await asyncio.gather(*[fetch_one(p) for p in pages[:limit]])

    urls_seen = set()
    page_scores = []
    desktop_checked = 0
    field_pages = set()
    lab_pages = set()
    field_avgs = {"lcp": [], "inp": [], "cls": []}
    cwv_avgs = {"lcp": [], "inp": [], "cls": []}
    for r in results:
        if r.get("strategy") == "desktop":
            desktop_checked += 1
            continue
        if r.get("url") in urls_seen:
            continue
        urls_seen.add(r.get("url"))
        if r.get("cwv_score") is not None:
            page_scores.append(r["cwv_score"])
        field = r.get("field") or {}
        if field.get("lcp") is not None or field.get("inp") is not None or field.get("cls") is not None:
            field_pages.add(r.get("url"))
            for k in field_avgs:
                if k in field and field[k] is not None:
                    field_avgs[k].append(field[k])
        else:
            lab_pages.add(r.get("url"))
            
        cwv = r.get("cwv") or {}
        for k in cwv_avgs:
            if k in cwv and cwv[k] is not None:
                cwv_avgs[k].append(cwv[k])

    summary = {
        "job_id": job_id,
        "checks": len(results),
        "pages_checked": len(urls_seen),
        "desktop_checked": desktop_checked,
        "pages": limit,
        "failed": len(errors),
        "errors": errors[:10],
        "avg_cwv_score": round(sum(page_scores) / len(page_scores), 1) if page_scores else None,
        "cwv_sources": {
            src: sum(1 for r in results if r.get("strategy") == "mobile" and r.get("cwv_source") == src)
            for src in ("field", "lab", "mixed", "partial")
        },
        "pages_total": len(pages),
        "sample_size": limit,
        "cwv_passed_pages": sum(1 for r in results if r.get("strategy") == "mobile" and (r.get("cwv_assessment") or {}).get("overall") == "passed"),
        "cwv_failed_pages": sum(1 for r in results if r.get("strategy") == "mobile" and (r.get("cwv_assessment") or {}).get("overall") == "failed"),
        "field_pages": len(field_pages),
        "lab_only_pages": len(lab_pages),
        "field_avg": {
            k: round(sum(vs) / len(vs), 1) if vs else None
            for k, vs in field_avgs.items()
        },
        "cwv_avg": {
            k: round(sum(vs) / len(vs), 3) if vs else None
            for k, vs in cwv_avgs.items()
        },
    }
    await db.page_performance_summaries.update_one(
        {"job_id": job_id},
        {"$set": {"job_id": job_id, **summary}},
        upsert=True,
    )
    return summary


async def get_performance_summary(job_id: str) -> dict | None:
    db = get_db()
    doc = await db.page_performance_summaries.find_one({"job_id": job_id})
    if doc:
        doc["id"] = str(doc.pop("_id"))
    return doc
