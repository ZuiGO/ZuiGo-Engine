"""Content Freshness & Decay Tracking.

Flags pages that have not been updated recently (based on last_modified headers
or sitemap lastmod), prioritizing high-value pages.
"""

from datetime import datetime, timedelta
from backend.db.mongo import get_db
from backend.logging_setup import get_logger

logger = get_logger("freshness")

async def audit_content_freshness(job_id: str) -> dict:
    """Audits pages for freshness decay (older than 6 months)."""
    db = get_db()
    
    # 1. Fetch pages with last_modified dates
    cursor = db.pages.find(
        {"job_id": job_id, "last_modified": {"$ne": None}, "is_indexable": True},
        {"url": 1, "last_modified": 1, "page_type": 1}
    )
    
    decayed_pages = []
    fresh_pages = 0
    total_tracked = 0
    
    six_months_ago = datetime.utcnow() - timedelta(days=180)
    
    async for page in cursor:
        total_tracked += 1
        lm = page.get("last_modified")
        if isinstance(lm, datetime):
            if lm < six_months_ago:
                decayed_pages.append({
                    "url": page["url"],
                    "last_modified": lm,
                    "page_type": page.get("page_type")
                })
            else:
                fresh_pages += 1
                
    # Sort decayed pages, oldest first
    decayed_pages.sort(key=lambda x: x["last_modified"])
    
    # Measured share of dated pages modified within the last 180 days. Pages with no usable date are
    # not scored (and no date at all means no score, not a perfect one).
    dated = fresh_pages + len(decayed_pages)
    score = round(100 * fresh_pages / dated) if dated else None

    summary = {
        "status": "audited",
        "total_pages_with_dates": total_tracked,
        "fresh_pages": fresh_pages,
        "decayed_pages_count": len(decayed_pages),
        "decayed_pages": decayed_pages[:50], # Keep top 50 oldest
        "score": score,
        "basis": "share of pages whose Last-Modified date is within 180 days; only as truthful as the site's Last-Modified headers",
    }

    await db.content_freshness.update_one(
        {"job_id": job_id},
        {"$set": {"job_id": job_id, **summary}},
        upsert=True
    )
    
    return summary
