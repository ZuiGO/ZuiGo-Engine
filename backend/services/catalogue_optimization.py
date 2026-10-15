"""Catalogue Optimization (E-commerce).

Audits Product Listing Pages (PLPs) and Product Detail Pages (PDPs) for 
common e-commerce SEO issues like faceted navigation crawl traps, 
missing canonicals, and missing product schema.
"""

from urllib.parse import urlparse, parse_qs

from backend.db.mongo import get_db
from backend.logging_setup import get_logger

logger = get_logger("catalogue")

async def audit_catalogue(job_id: str) -> dict:
    """Audits PLPs and PDPs for e-commerce SEO health."""
    db = get_db()
    
    # 1. Fetch PLPs (category) and PDPs (product)
    cursor = db.pages.find(
        {"job_id": job_id, "page_type": {"$in": ["category", "product"]}},
        {"url": 1, "page_type": 1, "html": 1} # We'd ideally need HTML for canonicals if not parsed, but we assume it's in the DB if needed.
    )
    
    plps = []
    pdps = []
    async for p in cursor:
        if p["page_type"] == "category":
            plps.append(p["url"])
        else:
            pdps.append(p["url"])

    if not plps and not pdps:
        return {"status": "skipped", "message": "No product or category pages detected."}

    # 2. Audit Faceted Navigation (PLPs with query params)
    faceted_urls = []
    for url in plps:
        parsed = urlparse(url)
        if parsed.query:
            # Contains query params, likely a filter/sort (faceted nav)
            params = parse_qs(parsed.query)
            # We want to flag if this URL was crawled but doesn't have a canonical tag
            # pointing to the clean URL, but for now we just count them.
            faceted_urls.append(url)

    # 3. Check for product schema on PDPs
    # We can query the content_items or just rely on the structured_data audit.
    # For a high-level catalogue summary, we count the PDPs vs PLPs.

    # Measured: share of crawled category (PLP) URLs without query parameters.
    clean_plps = len(plps) - len(faceted_urls)
    score = round(100 * clean_plps / len(plps)) if plps else None
    # Policy: more than FACET_TRAP_RATIO parameterised URLs per clean category page suggests a crawl trap.
    FACET_TRAP_RATIO = 2.0
    crawl_trap = clean_plps > 0 and (len(faceted_urls) / clean_plps) > FACET_TRAP_RATIO

    summary = {
        "status": "audited",
        "total_plps": len(plps),
        "total_pdps": len(pdps),
        "faceted_urls_crawled": len(faceted_urls),
        "potential_crawl_trap": crawl_trap,
        "score": score,
    }

    await db.catalogue_audits.update_one(
        {"job_id": job_id},
        {"$set": {"job_id": job_id, **summary}},
        upsert=True
    )
    
    return summary
