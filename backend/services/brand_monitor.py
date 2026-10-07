"""Brand & Reputation Watch.

Monitors SERP snippets for branded queries to detect sentiment (positive, neutral, negative)
and alert on potential reputation issues.
"""

from urllib.parse import urlparse
import json

from backend.db.mongo import get_db
from backend.logging_setup import get_logger
from backend.services.serp_api import search_keyword
from backend.services.agent_planner import _generate_groq

logger = get_logger("brand_monitor")

async def monitor_brand_reputation(job_id: str, url: str) -> dict:
    """Monitors SERPs for brand sentiment."""
    db = get_db()
    
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    if domain.startswith("www."):
        domain = domain[4:]
        
    company_name = domain.split(".")[0].replace("-", " ")
    
    queries = [
        f'"{company_name}" reviews',
        f'"{company_name}" scam OR legit OR complaints'
    ]
    
    snippets_to_analyze = []
    
    for q in queries:
        try:
            serp_data = await search_keyword(q)
            for res in serp_data.get("top_results", [])[:5]:
                # Don't analyze the company's own site
                if domain not in res.get("url", ""):
                    snippets_to_analyze.append(res.get("title", ""))
        except Exception as e:
            logger.warning(f"Failed to fetch SERP for reputation query '{q}': {e}")
            
    if not snippets_to_analyze:
        return {"status": "skipped", "message": "No third-party reputation snippets found."}
        
    # Ask LLM to classify sentiment
    snippets_text = chr(10).join(f"- {s}" for s in snippets_to_analyze)
    prompt = f"""You are an expert PR and Brand Reputation analyst.
Analyze these search engine result snippets about the company "{company_name}":

{snippets_text}

Determine the overall sentiment of these search results.
Return a JSON object with:
1. "sentiment": "positive", "neutral", or "negative"
2. "risk_score": an integer from 0 to 100 (where 100 is extremely negative/high risk)
3. "summary": A 1-sentence explanation of what people are saying.

JSON:"""

    sentiment = "neutral"
    risk_score = 0
    summary_text = "No clear sentiment detected."
    
    try:
        llm_response = await _generate_groq(prompt, max_tokens=150, temperature=0.1)
        import re
        json_match = re.search(r"\{.*\}", llm_response, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group(0))
            sentiment = result.get("sentiment", "neutral")
            risk_score = result.get("risk_score", 0)
            summary_text = result.get("summary", summary_text)
    except Exception as e:
        logger.error(f"Failed to analyze reputation sentiment for {company_name}: {e}")

    summary = {
        "status": "monitored",
        "company_name": company_name,
        "sentiment": sentiment,
        "risk_score": risk_score,
        "summary": summary_text,
        "snippets_analyzed": len(snippets_to_analyze)
    }
    
    await db.brand_reputation.update_one(
        {"job_id": job_id},
        {"$set": {"job_id": job_id, **summary}},
        upsert=True
    )
    
    return summary
