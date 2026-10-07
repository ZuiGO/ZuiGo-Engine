"""B2B Profile & Citation Building Audit.

Checks for the existence of the company domain on major B2B directories
and networks to ensure NAP consistency and profile presence.
"""

from urllib.parse import urlparse
from backend.db.mongo import get_db
from backend.logging_setup import get_logger
from backend.services.serp_api import search_keyword

logger = get_logger("citation_audit")

B2B_DIRECTORIES = {
    "LinkedIn": "linkedin.com/company",
    "Crunchbase": "crunchbase.com/organization",
    "YellowPages": "yellowpages.com",
    "Yelp": "yelp.com/biz",
    "Clutch": "clutch.co/profile",
    "Trustpilot": "trustpilot.com/review"
}

async def audit_citations(job_id: str, url: str) -> dict:
    """Audits the presence of the company on major B2B directories."""
    db = get_db()
    
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    if domain.startswith("www."):
        domain = domain[4:]
        
    company_name = domain.split(".")[0].replace("-", " ")

    results = []
    found_count = 0
    
    for name, site in B2B_DIRECTORIES.items():
        query = f'"{domain}" OR "{company_name}" site:{site}'
        try:
            # We don't want to burn too many SERP credits, so we only fetch organic count
            # A more robust system would use Google Places API for NAP consistency.
            serp_data = await search_keyword(query)
            
            # If total_results > 0 or organic_count > 0, we assume the profile exists
            exists = serp_data.get("organic_count", 0) > 0
            
            results.append({
                "directory": name,
                "expected_domain": site,
                "found": exists,
                "top_url": serp_data.get("top_results", [{}])[0].get("url") if exists and serp_data.get("top_results") else None
            })
            if exists:
                found_count += 1
                
        except Exception as e:
            logger.warning(f"Failed to check citation for {name}: {e}")
            results.append({
                "directory": name,
                "expected_domain": site,
                "found": False,
                "error": str(e)
            })
            
    score = int((found_count / len(B2B_DIRECTORIES)) * 100) if B2B_DIRECTORIES else 0
    
    summary = {
        "status": "audited",
        "company_name": company_name,
        "directories_checked": len(B2B_DIRECTORIES),
        "profiles_found": found_count,
        "results": results,
        "score": score
    }
    
    await db.citation_audits.update_one(
        {"job_id": job_id},
        {"$set": {"job_id": job_id, **summary}},
        upsert=True
    )
    
    return summary
