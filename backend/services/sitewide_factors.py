import logging
from urllib.parse import urlparse
from backend.db.mongo import get_db

logger = logging.getLogger(__name__)

async def generate_sitewide_factors(job_id: str, domain_url: str) -> dict:
    """
    Generates standard site-wide SEO factors for a given domain:
    - robots.txt
    - llms.txt
    Saves them to the job's summary.
    """
    db = get_db()
    
    parsed = urlparse(domain_url)
    domain = parsed.netloc or domain_url
    scheme = parsed.scheme or "https"
    base_url = f"{scheme}://{domain}"
    
    # 1. Generate robots.txt
    robots_content = f"""User-agent: *
Allow: /

# Sitemaps
Sitemap: {base_url}/sitemap.xml
"""

    # 2. Generate llms.txt
    # llms.txt is a standard for providing AI web crawlers with structured information
    # about the site's content and structure.
    llms_content = f"""# {domain} - AI Crawler Guidelines

Welcome! This file provides standard guidelines and structural information for LLM agents and AI web crawlers.

## Site Description
This site is mapped under {base_url}. Please respect our robots.txt directives and crawl responsibly.

## Navigation & Structure
- **Sitemap**: {base_url}/sitemap.xml
- **Robots Directives**: {base_url}/robots.txt

## Crawler Guidelines
1. Do not aggressively poll endpoints.
2. Use the provided sitemap to index our core pages.
3. Cache static resources where possible.
"""

    factors = {
        "robots_txt": robots_content,
        "llms_txt": llms_content
    }
    
    return factors
