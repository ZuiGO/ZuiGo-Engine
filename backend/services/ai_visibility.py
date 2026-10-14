"""AI-search visibility readiness: checks whether the site is citable by
generative engines — robots rules for AI crawlers (section-aware parsing),
structured data counted from real JSON-LD scripts, plain extractable text,
sitemap + llms.txt presence. Offline heuristics only (no paid AI-overview
monitoring API).
"""

import re
from collections import Counter
from datetime import datetime

from bs4 import BeautifulSoup

from backend.db.mongo import get_db
from backend.logging_setup import get_logger
from backend.services.content_signals import compute_page_signals
from backend.services.robots_rules import AI_CRAWLERS, ANSWER_ENGINE_PURPOSES, parse_robots
from backend.services.structured_data import detect_structured_data

logger = get_logger("ai_visibility")

# Reference list shared with geo_readiness (see robots_rules.AI_CRAWLERS).
AI_AGENTS = [name.lower() for name, _, _ in AI_CRAWLERS]
TRAINING_ONLY_AGENTS = {name.lower() for name, _, purpose in AI_CRAWLERS if purpose == "training"}
ANSWER_ENGINE_AGENTS = {name.lower() for name, _, purpose in AI_CRAWLERS if purpose in ANSWER_ENGINE_PURPOSES}
ANSWER_BLOCK_WORDS = (40, 60)
DEFINITION_BLOCK_WORDS = (30, 80)
FRESHNESS_DAYS = 183
MAX_SCAN_PAGES = 50

def _ld_types(html: str) -> set[str]:
    """Lower-cased structured-data types (JSON-LD, Microdata, RDFa) found in a page."""
    return {t.lower() for t in detect_structured_data(html or "")["types"]}


def _word_count(text: str) -> int:
    return len((text or "").split())


def _parse_date(value: str) -> datetime | None:
    v = (value or "").strip()
    if not v:
        return None
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%a, %d %b %Y %H:%M:%S %z",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(v, fmt)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(v.replace("Z", "+00:00"))
        return parsed
    except ValueError:
        return None


def _uttcnow_naive() -> datetime:
    return datetime.utcnow()


def _is_fresh(value: str, now: datetime | None = None) -> bool:
    parsed = _parse_date(value)
    if parsed is None:
        return False
    if parsed.tzinfo is not None:
        parsed = parsed.replace(tzinfo=None)
    now = now or _uttcnow_naive()
    return (now - parsed).days <= FRESHNESS_DAYS


def _ai_extractability(html: str) -> dict:
    """ai-seo skill Pillar 1/2 signals from one page — extractable structure,
    authority (author + freshness), and agent-friendly semantics."""
    soup = BeautifulSoup(html or "", "lxml")
    paragraphs = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
    paragraphs = [p for p in paragraphs if p]

    answer_blocks = sum(1 for t in paragraphs if ANSWER_BLOCK_WORDS[0] <= _word_count(t) <= ANSWER_BLOCK_WORDS[1])
    first = paragraphs[0] if paragraphs else ""
    definition_first = (
        DEFINITION_BLOCK_WORDS[0] <= _word_count(first) <= DEFINITION_BLOCK_WORDS[1]
        if first
        else False
    )
    faq_headings = sum(
        1 for h in soup.find_all(["h2", "h3"]) if (h.get_text(" ", strip=True).strip().endswith("?"))
    )
    comparison_tables = len(soup.select("table"))
    stat_cited = 0
    for p in soup.find_all("p"):
        text = p.get_text(" ", strip=True)
        if re.search(r"\d", text) and text.find(" ") > 0 and p.find("a"):
            stat_cited += 1
    author = bool(soup.select_one('meta[name="author"], meta[property="article:author"]'))
    fresh = False
    for sel in (
        'meta[property="article:modified_time"]',
        'meta[name="last-modified"]',
        'meta[property="article:published_time"]',
    ):
        node = soup.select_one(sel)
        if node and _is_fresh(node.attrs.get("content") or ""):
            fresh = True
            break
    if not fresh:
        for t in soup.select("time[datetime]"):
            if _is_fresh(t.attrs.get("datetime") or ""):
                fresh = True
                break
    landmarks = bool(soup.select("main, article, nav"))
    return {
        "answer_block": answer_blocks,
        "definition_first": definition_first,
        "faq_heading": faq_headings,
        "comparison_table": comparison_tables,
        "stat_cited": stat_cited,
        "author": author,
        "fresh": fresh,
        "semantic_landmark": landmarks,
    }


async def _fetch_plain(url: str, user_agent: str, auth: tuple[str, str] | None = None) -> tuple[str | None, int | None]:
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True, auth=auth) as client:
            resp = await client.get(url, headers={"User-Agent": user_agent})
        if resp.status_code == 200:
            return resp.text, resp.status_code
        return None, resp.status_code
    except Exception:
        return None, None


async def check_ai_visibility(job_id: str, target_url: str, http_username: str | None = None, http_password: str | None = None) -> dict:
    db = get_db()
    from urllib.parse import urlparse as _urlparse

    _u = _urlparse(target_url if "//" in target_url else "https://" + target_url)
    domain = _u.netloc
    origin = f"{_u.scheme or 'https'}://{domain}"
    auth = (http_username, http_password) if http_username and http_password else None
    robots_txt, robots_status = await _fetch_plain(origin + "/robots.txt", "ZuiGO-Engine/1.0 ai-visibility", auth=auth)

    # RFC 9309: a missing (4xx) robots.txt means no restrictions; a 5xx / failed fetch means we cannot tell.
    robots_measured = robots_txt is not None or (robots_status is not None and 400 <= robots_status < 500)
    rules = parse_robots(robots_txt)
    agent_rows = []
    for name, org, purpose in AI_CRAWLERS:
        d = rules.check(name, "/")
        agent_rows.append({
            "agent": name.lower(),
            "org": org,
            "purpose": purpose,
            "status": "blocked" if not d.allowed else ("partial" if d.restricted_patterns else "allowed"),
            "rule": d.rule,
            "group": d.group,
            "disallow_rules": len(d.restricted_patterns),
            "sample_rules": d.restricted_patterns[:4],
        })
    # Only answer-engine crawlers count as a "block" problem; blocking training-only crawlers is a policy choice.
    blocked_agents = [r["agent"] for r in agent_rows if r["status"] == "blocked" and r["agent"] in ANSWER_ENGINE_AGENTS]
    allowed_agents = [r["agent"] for r in agent_rows if r["status"] != "blocked"]
    blocked_training_agents = [r["agent"] for r in agent_rows if r["agent"] in TRAINING_ONLY_AGENTS and r["status"] == "blocked"]
    answer_rows = [r for r in agent_rows if r["agent"] in ANSWER_ENGINE_AGENTS]
    crawl_access_pct = round(100 * sum(1 for r in answer_rows if r["status"] != "blocked") / len(answer_rows)) if robots_measured else None

    pages = await db.pages.find({"job_id": job_id}, {"html": 1, "url": 1, "status_code": 1}).to_list(length=None)
    pages = [p for p in pages if (p.get("status_code") or 200) < 400]  # error pages carry no content signals
    with_structured = 0
    extractable_plain = 0
    schema_counter: Counter[str] = Counter()
    ai_ext = Counter()
    scanned = 0
    for p in pages:
        html = p.get("html") or ""
        if not html:
            continue
        types = _ld_types(html)
        if types:
            with_structured += 1
            schema_counter.update(types)
        signals = compute_page_signals(html)
        if signals.get("extractable_format"):
            extractable_plain += 1
        if scanned < MAX_SCAN_PAGES:
            ex = _ai_extractability(html)
            for key, val in ex.items():
                if val is True:
                    ai_ext[key + "_pages"] += 1
                elif isinstance(val, int) and val > 0:
                    ai_ext[key + "_pages"] += 1
            scanned += 1

    llms_txt, llms_status = await _fetch_plain(origin + "/llms.txt", "ZuiGO-Engine/1.0 ai-visibility", auth=auth)
    pricing_md, pricing_md_status = await _fetch_plain(origin + "/pricing.md", "ZuiGO-Engine/1.0 ai-visibility", auth=auth)
    pricing_txt, pricing_txt_status = await _fetch_plain(origin + "/pricing.txt", "ZuiGO-Engine/1.0 ai-visibility", auth=auth)
    okf_html, okf_status = await _fetch_plain(origin + "/okf/", "ZuiGO-Engine/1.0 ai-visibility", auth=auth)
    okf_present = okf_html is not None and len(okf_html.strip()) > 0

    total = max(len(pages), 1)
    sitemap_doc = await db.sitemap_audits.find_one({"job_id": job_id})
    sitemap_ok = False
    if sitemap_doc and sitemap_doc.get("sitemap_valid"):
        sitemap_ok = True
    else:
        from backend.services.sitemap import _robots_sitemap_urls, _fetch, _parse_sitemap_urls
        candidates = await _robots_sitemap_urls(origin, auth=auth)
        candidates.append(origin + "/sitemap.xml")
        for cand in candidates:
            text = await _fetch(cand, auth=auth)
            if text:
                urls = await _parse_sitemap_urls(text, auth=auth)
                if urls:
                    sitemap_ok = True
                    break

    has_pages = len(pages) > 0
    struct_ratio = with_structured / total
    extract_ratio = extractable_plain / total
    # Each component is a measured 0-100 value (or None when it could not be measured).
    # The score is their unweighted mean: no invented weights, no pass/fail cut-offs,
    # and unmeasured components are left out instead of being scored as 0 or 100.
    subscores = {
        "crawl_access": crawl_access_pct,
        "sitemap": 100 if sitemap_ok else 0,
        "structured_data": round(100 * struct_ratio) if has_pages else None,
        "extractable_content": round(100 * extract_ratio) if has_pages else None,
    }
    measured = [v for v in subscores.values() if v is not None]
    score = round(sum(measured) / len(measured)) if measured else None

    checks = [
        {
            "passed": sitemap_ok,
            "label": "The site exposes a valid XML sitemap",
            "detail": (
                f"Sitemap lists {(sitemap_doc or {}).get('pages_in_sitemap', 0)} URLs for AI crawlers."
                if sitemap_ok
                else "Add or repair an XML sitemap (and reference it in robots.txt) so AI crawlers index every page."
            ),
        },
        {
            "passed": llms_txt is not None,
            "label": "The site publishes an llms.txt file (informational, not scored)",
            "detail": "llms.txt lists pages for LLM consumers."
                      if llms_txt else "Add an llms.txt file at /llms.txt so LLM products can cite the pages.",
        },
        {
            "passed": struct_ratio >= 0.5,
            "label": "Structured data on at least half of crawled pages",
            "detail": f"JSON-LD containing @type found on {with_structured} of {total} crawled pages.",
        },
        {
            "passed": extract_ratio >= 0.5,
            "label": "Verbatim-extractable content (FAQ / tables / lists)",
            "detail": f"{extractable_plain} of {total} pages contain extractable structure (FAQ, tables, lists).",
        },
    ]
    if blocked_agents:
        checks.append({
            "passed": False,
            "label": "robots.txt does not block AI agents",
            "detail": f"robots.txt fully blocks: {', '.join(blocked_agents[:5])}.",
        })

    scanned_ratio = scanned / total if scanned else 0
    pricing_ratio = (ai_ext["author_pages"] / scanned) if scanned else 0
    fresh_ratio = (ai_ext["fresh_pages"] / scanned) if scanned else 0
    answer_ratio = (ai_ext["answer_block_pages"] / scanned) if scanned else 0

    checks.extend([
        {
            "passed": pricing_md is not None or pricing_txt is not None,
            "label": "Machine-readable pricing for AI agents",
            "detail": (
                "pricing.md is published for AI agents to parse."
                if pricing_md is not None
                else ("pricing.txt is published for AI agents to parse."
                      if pricing_txt is not None
                      else "Add a /pricing.md (or /pricing.txt) file so buying agents can compare your plans.")
            ),
        },
        {
            "passed": answer_ratio >= 0.3,
            "label": "Answer blocks (40-60 word passages) on content pages",
            "detail": (
                f"{ai_ext['answer_block_pages']} of {scanned} scanned pages contain self-contained answer blocks."
                if scanned
                else "No content pages scanned."
            ),
        },
        {
            "passed": pricing_ratio >= 0.3,
            "label": "Author attribution on content pages",
            "detail": (
                f"{ai_ext['author_pages']} of {scanned} scanned pages name an author."
                if scanned
                else "No content pages scanned."
            ),
        },
        {
            "passed": fresh_ratio >= 0.3,
            "label": "Freshness signals (last-updated within 6 months)",
            "detail": (
                f"{ai_ext['fresh_pages']} of {scanned} scanned pages show a recent update date."
                if scanned
                else "No content pages scanned."
            ),
        },
    ])
    if blocked_training_agents:
        checks.append({
            "passed": False,
            "label": "robots.txt blocks training-only crawlers",
            "detail": (
                f"robots.txt blocks training-only crawler(s): {', '.join(blocked_training_agents)}. "
                "This is a defensible business choice (blocks training, allows citation) — "
                "verify search-and-cite bots (GPTBot, PerplexityBot, ClaudeBot) stay allowed."
            ),
        })

    summary = {
        "job_id": job_id,
        "url": target_url,
        "score": score,
        "subscores": subscores,
        "score_basis": "unweighted mean of the measured components in subscores (each 0-100)",
        "checks": checks,
        "robots_txt_found": robots_txt is not None,
        "robots_status": robots_status,
        "ai_agents": agent_rows,
        "blocked_ai_agents": blocked_agents,
        "allowed_ai_agents": allowed_agents,
        "blocked_training_agents": blocked_training_agents,
        "ai_agents_scanned": AI_AGENTS,
        "answer_engine_agents": sorted(ANSWER_ENGINE_AGENTS),
        "llms_txt_present": llms_txt is not None,
        "llms_txt_status": llms_status,
        "pricing_md_present": pricing_md is not None,
        "pricing_md_status": pricing_md_status,
        "pricing_txt_present": pricing_txt is not None,
        "pricing_txt_status": pricing_txt_status,
        "okf_present": okf_present,
        "okf_status": okf_status,
        "structured_data_pages": with_structured,
        "extractable_pages": extractable_plain,
        "scanned_pages": scanned,
        "answer_block_pages": ai_ext["answer_block_pages"],
        "definition_first_pages": ai_ext["definition_first_pages"],
        "faq_heading_pages": ai_ext["faq_heading_pages"],
        "comparison_table_pages": ai_ext["comparison_table_pages"],
        "stat_cited_pages": ai_ext["stat_cited_pages"],
        "author_pages": ai_ext["author_pages"],
        "fresh_pages": ai_ext["fresh_pages"],
        "semantic_landmark_pages": ai_ext["semantic_landmark_pages"],
        "schema_types": dict(schema_counter.most_common(10)),
        "total_pages": len(pages),
        "sitemap_valid": sitemap_ok,
        "checked_at": datetime.utcnow(),
    }
    await db.ai_visibility_summaries.update_one(
        {"job_id": job_id},
        {"$set": summary},
        upsert=True,
    )
    logger.info("AI visibility job=%s score=%s blocked=%s", job_id, score, blocked_agents)
    return summary