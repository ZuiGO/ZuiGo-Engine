"""Search-Growth Content (Content Gap Creation).

Uses LLMs to generate SEO-optimized content outlines and ideas based on
keyword gaps or existing keyword themes.
"""

import json
from backend.db.mongo import get_db
from backend.logging_setup import get_logger
from backend.services.agent_planner import _generate_groq

logger = get_logger("content_growth")

async def generate_content_opportunities(job_id: str, domain: str) -> dict:
    """Generates content opportunities and outlines using LLM."""
    db = get_db()
    
    # 1. Try to find missing keywords from competitor analysis
    gap_docs = await db.competitor_gap_analyses.find(
        {"target_job_id": job_id, "status": "completed"}
    ).to_list(length=5)
    
    missing_keywords = set()
    for doc in gap_docs:
        ka = doc.get("se_rich", {}).get("keyword_analysis", {})
        for kw in ka.get("missing", []):
            if isinstance(kw, dict) and kw.get("keyword"):
                missing_keywords.add(kw["keyword"])
            elif isinstance(kw, str):
                missing_keywords.add(kw)
                
    # 2. Fallback to smart keywords if no competitor data
    if not missing_keywords:
        kw_doc = await db.job_keywords.find_one({"job_id": job_id})
        if kw_doc and kw_doc.get("smart_keywords"):
            missing_keywords = set(k["keyword"] for k in kw_doc["smart_keywords"][:20])
            
    if not missing_keywords:
        return {"status": "skipped", "message": "No keywords available for content generation."}

    target_keywords = list(missing_keywords)[:10]
    
    prompt = f"""You are an expert SEO Content Strategist.
I have a website on domain: {domain}
Based on keyword gap analysis, we need to target these keywords to grow our search traffic:
{chr(10).join(target_keywords)}

Generate 3 highly optimized Content Ideas (articles, guides, or landing pages) that target these keywords.
For each idea, provide:
1. "title": A catchy, SEO-optimized H1 title.
2. "target_keyword": The primary keyword it targets.
3. "intent": Informational, Transactional, or Commercial.
4. "outline": A list of 3-4 H2 subheadings for the content.

Return ONLY a JSON object with a single key "opportunities" containing a list of these 3 ideas.

JSON:"""

    opportunities = []
    try:
        llm_response = await _generate_groq(prompt, max_tokens=1000, temperature=0.5)
        import re
        json_match = re.search(r"\{.*\}", llm_response, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group(0))
            opportunities = result.get("opportunities", [])
    except Exception as e:
        logger.error(f"Failed to generate content opportunities for {domain}: {e}")
        
    summary = {
        "status": "generated",
        "opportunities": opportunities,
        "source_keywords_used": target_keywords
    }
    
    await db.content_opportunities.update_one(
        {"job_id": job_id},
        {"$set": {"job_id": job_id, **summary}},
        upsert=True
    )
    
    return summary
