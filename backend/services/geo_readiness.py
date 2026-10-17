"""AI-crawler access check (the "GEO readiness" signal).

Fetches robots.txt and evaluates, per RFC 9309, whether each known AI crawler
may fetch the homepage. This measures *crawl access only*. It says nothing about
whether any AI engine actually cites the site.

Score = share of *answer-engine* crawlers (purpose "search"/"user") that are
allowed to fetch "/". Training-only crawlers are reported separately: blocking
them is a policy choice, not a defect, so they do not lower the score.
"""

import httpx

from backend.logging_setup import get_logger
from backend.services.robots_rules import AI_CRAWLERS, ANSWER_ENGINE_PURPOSES, parse_robots

logger = get_logger("geo")

# Kept for backwards compatibility with callers that import it.
AI_AGENTS = [(name, org) for name, org, _ in AI_CRAWLERS]

USER_AGENT = "ZuiGO-EngineBot/1.0 (+https://zuigo.ai)"

BASIS = "robots.txt rules evaluated per RFC 9309 for the homepage path"
NOTE = (
    "Crawl access only: allowing an AI crawler is necessary for it to read the site "
    "but does not mean the site is cited. Not required for Google AI Overviews or AI Mode."
)


def check_robots_text(text: str) -> dict:
    rules = parse_robots(text)
    agents = []
    for name, org, purpose in AI_CRAWLERS:
        d = rules.check(name, "/")
        agents.append({
            "agent": name,
            "org": org,
            "purpose": purpose,
            "allowed": d.allowed,
            "group": d.group,
            "rule": d.rule,
            "restricted_paths": d.restricted_patterns[:5],
        })
    scored = [a for a in agents if a["purpose"] in ANSWER_ENGINE_PURPOSES]
    scored_allowed = [a for a in scored if a["allowed"]]
    blocked_scored = [a for a in scored if not a["allowed"]]
    blocked = [a["agent"] for a in agents if not a["allowed"]]
    allowed = [a["agent"] for a in agents if a["allowed"]]
    # "no rules": no tracked crawler is touched by any Allow/Disallow line.
    no_rules = all(a["rule"] is None and not a["restricted_paths"] for a in agents)

    if no_rules:
        status = "allowed-by-default"
    elif not scored_allowed:
        status = "blocked"
    elif blocked_scored:
        status = "partial"
    else:
        status = "allowed"

    return {
        "status": status,
        "score": round(100 * len(scored_allowed) / len(scored)),
        "robots_txt_found": True,
        "blocked_ai_crawlers": blocked,
        "allowed_ai_crawlers": allowed,
        "blocked_answer_engine_crawlers": [a["agent"] for a in blocked_scored],
        "blocked_training_crawlers": [a["agent"] for a in agents if not a["allowed"] and a["purpose"] == "training"],
        "ai_agents_scanned": [a["agent"] for a in agents],
        "agents": agents,
        "basis": BASIS,
        "note": NOTE,
    }


async def check_geo_readiness(url: str, timeout: float = 15.0, http_username: str | None = None, http_password: str | None = None) -> dict:
    """Fetch robots.txt for the site and run the AI-crawler access check."""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    auth = (http_username, http_password) if http_username and http_password else None
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, auth=auth) as client:
            resp = await client.get(origin + "/robots.txt", headers={"User-Agent": USER_AGENT})
    except Exception as e:
        logger.warning("GEO robots.txt fetch failed for %s: %s", origin, e)
        return {"status": "unknown", "score": None, "robots_txt_found": False, "error": str(e)[:200]}
    if 400 <= resp.status_code < 500:
        # RFC 9309 s2.3.1.3: a missing/unavailable (4xx) robots.txt means no restrictions.
        result = check_robots_text("")
        result["status"] = "allowed-by-default"
        result["robots_txt_found"] = False
        result["http_status"] = resp.status_code
        result["robots_txt_url"] = origin + "/robots.txt"
        return result
    if resp.status_code >= 500:
        # Server error: crawlers must assume full disallow temporarily -> we cannot tell.
        return {"status": "unknown", "score": None, "robots_txt_found": False, "http_status": resp.status_code}
    result = check_robots_text(resp.text)
    result["robots_txt_url"] = origin + "/robots.txt"
    return result
