"""Automated Crawl-Error Resolution (301 Redirect Mapping).

Analyzes 404/broken pages from the crawl and suggests 301 redirects to the
most relevant 200 OK pages using fuzzy matching and LLM refinement.
"""

import difflib
from urllib.parse import urlparse
import json

from backend.db.mongo import get_db
from backend.logging_setup import get_logger
from backend.services.agent_planner import _generate_groq

logger = get_logger("redirect_mapper")

async def generate_redirect_map(job_id: str) -> dict:
    """Finds all 404 pages and suggests the best 200 OK page to redirect to."""
    db = get_db()
    
    # 1. Fetch 404 pages
    broken_cursor = db.pages.find({"job_id": job_id, "status_code": 404}, {"url": 1})
    broken_urls = [p["url"] async for p in broken_cursor]
    
    if not broken_urls:
        return {"status": "ok", "mappings": [], "message": "No 404 pages found."}
        
    # 2. Fetch 200 OK indexable pages
    valid_cursor = db.pages.find(
        {"job_id": job_id, "status_code": 200, "is_indexable": True}, 
        {"url": 1, "title": 1, "page_type": 1}
    )
    valid_pages = [p async for p in valid_cursor]
    valid_urls = [p["url"] for p in valid_pages]
    
    if not valid_urls:
        return {"status": "error", "mappings": [], "message": "No valid 200 pages found to map to."}

    mappings = []
    
    # Pre-compute parsed paths for valid URLs
    valid_paths = {u: urlparse(u).path for u in valid_urls}
    valid_path_list = list(valid_paths.values())
    
    for broken_url in broken_urls:
        broken_path = urlparse(broken_url).path
        
        # 1. Fast heuristic: difflib close matches on the path
        matches = difflib.get_close_matches(broken_path, valid_path_list, n=3, cutoff=0.4)
        
        candidate_urls = []
        for m in matches:
            for u, p in valid_paths.items():
                if p == m:
                    candidate_urls.append(u)
                    
        # 2. If no fuzzy match, fallback to home page or highest level category
        if not candidate_urls:
            home = next((p["url"] for p in valid_pages if p.get("page_type") == "home"), valid_urls[0])
            mappings.append({
                "broken_url": broken_url,
                "suggested_redirect": home,
                "confidence": "low",
                "method": "fallback",
                "candidates": []
            })
            continue

        # 3. Use LLM to pick the absolute best match from the candidates
        prompt = f"""You are an expert technical SEO deciding on the best 301 redirect.
A user requested this broken URL (404): {broken_url}

Here are the closest valid URLs (200) found on the site:
{chr(10).join(candidate_urls)}

Which of these candidate URLs is the BEST semantic match for the broken URL?
Consider path structure, language, and user intent.
Return your answer as a JSON object with exactly two keys:
1. "best_url": The exact string of the chosen URL from the candidates.
2. "confidence": "high", "medium", or "low" based on how well it matches.

JSON:"""
        
        try:
            llm_response = await _generate_groq(prompt, max_tokens=150, temperature=0.1)
            # Find the JSON block
            import re
            json_match = re.search(r"\{.*\}", llm_response, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group(0))
                best_url = result.get("best_url")
                confidence = result.get("confidence", "low")
                if best_url in candidate_urls:
                    mappings.append({
                        "broken_url": broken_url,
                        "suggested_redirect": best_url,
                        "confidence": confidence,
                        "method": "llm_fuzzy",
                        "candidates": candidate_urls
                    })
                    continue
        except Exception as e:
            logger.warning(f"LLM redirect mapping failed for {broken_url}: {e}")
            
        # Fallback to the first fuzzy match if LLM fails or doesn't return a valid candidate
        mappings.append({
            "broken_url": broken_url,
            "suggested_redirect": candidate_urls[0],
            "confidence": "medium",
            "method": "fuzzy",
            "candidates": candidate_urls
        })

    # Save to db
    await db.redirect_maps.update_one(
        {"job_id": job_id},
        {"$set": {"job_id": job_id, "mappings": mappings}},
        upsert=True
    )
        
    return {"status": "ok", "mappings": mappings, "message": f"Mapped {len(mappings)} URLs."}
