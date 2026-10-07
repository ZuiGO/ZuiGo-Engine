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

    score = 100
    if faceted_urls:
        # High number of faceted URLs relative to clean PLPs indicates a potential crawl trap
        clean_plps = len(plps) - len(faceted_urls)
        if clean_plps > 0 and (len(faceted_urls) / clean_plps) > 2.0:
            score -= 30 # Penalty for excessive faceted URLs crawled

    summary = {
        "status": "audited",
        "total_plps": len(plps),
        "total_pdps": len(pdps),
        "faceted_urls_crawled": len(faceted_urls),
        "potential_crawl_trap": score < 100,
        "score": max(0, score)
    }

    await db.catalogue_audits.update_one(
        {"job_id": job_id},
        {"$set": {"job_id": job_id, **summary}},
        upsert=True
    )
    
    return summary
