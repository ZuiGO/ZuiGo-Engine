import asyncio
import json
import uuid
from typing import Any
from bs4 import BeautifulSoup

from backend.config import settings
from backend.db.mongo import get_db
from backend.logging_setup import get_logger
from backend.services.agent_tools.tool_registry import ToolSpec, registry

logger = get_logger("domain_tools")

# ----------------- CRAWL DOMAIN -----------------

async def _crawl_full_site_tool(job_id: str, target_url: str, max_pages: int = 50) -> dict:
    from backend.services.crawler import crawl_site
    try:
        summary = await crawl_site(job_id, target_url, max_pages=max_pages, seed_sitemap=True, unlimited=False, mobile=True)
        return {"ok": True, "summary": summary}
    except Exception as e:
        logger.error("crawl_full_site_tool error: %s", e)
        return {"ok": False, "error": str(e)}

registry.register(ToolSpec(
    name="crawl_full_site",
    description="Crawl an entire website starting from a target URL up to max_pages. Discovers and indexes pages.",
    parameters={
        "type": "object",
        "properties": {
            "job_id": {"type": "string"},
            "target_url": {"type": "string"},
            "max_pages": {"type": "integer", "default": 50}
        },
        "required": ["job_id", "target_url"]
    },
    handler=_crawl_full_site_tool
))

# ----------------- ANALYSIS DOMAIN -----------------

async def _run_full_analysis_tool(job_id: str, url: str, max_pages: int = 50) -> dict:
    from backend.routes.analysis import run_analysis_pipeline
    try:
        # Note: this blocks the agent while the 12-wave pipeline completes.
        await run_analysis_pipeline(job_id, url, max_pages)
        return {"ok": True, "message": "Analysis pipeline completed successfully."}
    except Exception as e:
        logger.error("run_full_analysis_tool error: %s", e)
        return {"ok": False, "error": str(e)}

registry.register(ToolSpec(
    name="run_full_analysis",
    description="Run the full 12-wave SEO analysis pipeline for a job. Note: This takes several minutes to complete.",
    parameters={
        "type": "object",
        "properties": {
            "job_id": {"type": "string"},
            "url": {"type": "string"},
            "max_pages": {"type": "integer", "default": 50}
        },
        "required": ["job_id", "url"]
    },
    handler=_run_full_analysis_tool
))

async def _run_single_page_analysis_tool(url: str, job_id: str) -> dict:
    from backend.services.single_page_service import run_single_page_analysis
    try:
        await run_single_page_analysis(url, job_id)
        return {"ok": True, "message": "Single page analysis completed."}
    except Exception as e:
        logger.error("run_single_page_analysis_tool error: %s", e)
        return {"ok": False, "error": str(e)}

registry.register(ToolSpec(
    name="run_single_page_analysis",
    description="Run the single page analysis (generates AI suggestions and builds visual comparison).",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "job_id": {"type": "string"}
        },
        "required": ["url", "job_id"]
    },
    handler=_run_single_page_analysis_tool
))

# ----------------- INSIGHTS DOMAIN -----------------

async def _fetch_seo_insights_tool(domain: str, job_id: str) -> dict:
    from backend.services.external_insights import fetch_all_insights
    try:
        insights = await fetch_all_insights(domain, job_id)
        return _compact({"ok": True, "insights": insights})
    except Exception as e:
        logger.error("fetch_seo_insights_tool error: %s", e)
        return {"ok": False, "error": str(e)}

registry.register(ToolSpec(
    name="fetch_seo_insights",
    description="Fetch external SEO insights (SE Ranking, Google Search Console) for a domain.",
    parameters={
        "type": "object",
        "properties": {
            "domain": {"type": "string"},
            "job_id": {"type": "string"}
        },
        "required": ["domain", "job_id"]
    },
    handler=_fetch_seo_insights_tool
))

async def _run_serp_rankings_tool(domain: str, job_id: str, max_keywords: int = 10) -> dict:
    from backend.services.serp_api import run_serp_rankings
    try:
        results, errors = await run_serp_rankings(domain, job_id, max_keywords)
        return _compact({"ok": True, "results": results, "errors": errors})
    except Exception as e:
        logger.error("run_serp_rankings_tool error: %s", e)
        return {"ok": False, "error": str(e)}

registry.register(ToolSpec(
    name="run_serp_rankings",
    description="Check SERP rankings for the top keywords identified for the job.",
    parameters={
        "type": "object",
        "properties": {
            "domain": {"type": "string"},
            "job_id": {"type": "string"},
            "max_keywords": {"type": "integer", "default": 10}
        },
        "required": ["domain", "job_id"]
    },
    handler=_run_serp_rankings_tool
))

async def _audit_technical_tool(job_id: str) -> dict:
    from backend.services.site_health import compute_site_health
    try:
        health = await compute_site_health(job_id)
        return _compact({"ok": True, "health": health})
    except Exception as e:
        logger.error("audit_technical_tool error: %s", e)
        return {"ok": False, "error": str(e)}

registry.register(ToolSpec(
    name="audit_technical",
    description="Compute technical site health score and identify critical issues based on the crawl data.",
    parameters={
        "type": "object",
        "properties": {
            "job_id": {"type": "string"}
        },
        "required": ["job_id"]
    },
    handler=_audit_technical_tool
))

# ----------------- COMPETITOR DOMAIN -----------------

async def _run_competitor_audit_tool(job_id: str, competitors: list[str]) -> dict:
    from backend.services.competitor_audit import audit_competitors
    try:
        results = await audit_competitors(job_id, competitors)
        return _compact({"ok": True, "results": results})
    except Exception as e:
        logger.error("run_competitor_audit_tool error: %s", e)
        return {"ok": False, "error": str(e)}

registry.register(ToolSpec(
    name="run_competitor_audit",
    description="Run a deep analysis on a set of competitor URLs against a target job to identify gaps and opportunities.",
    parameters={
        "type": "object",
        "properties": {
            "job_id": {"type": "string"},
            "competitors": {"type": "array", "items": {"type": "string"}}
        },
        "required": ["job_id", "competitors"]
    },
    handler=_run_competitor_audit_tool
))

# ----------------- TECHNICAL DOMAIN -----------------

async def _audit_programmatic_tool(job_id: str) -> dict:
    from backend.services.programmatic_seo import audit_programmatic_seo
    try:
        results = await audit_programmatic_seo(job_id)
        return _compact({"ok": True, "results": results})
    except Exception as e:
        logger.error("audit_programmatic_tool error: %s", e)
        return {"ok": False, "error": str(e)}

registry.register(ToolSpec(
    name="audit_programmatic",
    description="Detect and evaluate programmatic page templates across the crawled site.",
    parameters={
        "type": "object",
        "properties": {
            "job_id": {"type": "string"}
        },
        "required": ["job_id"]
    },
    handler=_audit_programmatic_tool
))

async def _audit_ai_visibility_tool(job_id: str, target_url: str) -> dict:
    from backend.services.ai_visibility import check_ai_visibility
    try:
        results = await check_ai_visibility(job_id, target_url)
        return _compact({"ok": True, "results": results})
    except Exception as e:
        logger.error("audit_ai_visibility_tool error: %s", e)
        return {"ok": False, "error": str(e)}

registry.register(ToolSpec(
    name="audit_ai_visibility",
    description="Check LLM and Search Generative Experience visibility for a given URL.",
    parameters={
        "type": "object",
        "properties": {
            "job_id": {"type": "string"},
            "target_url": {"type": "string"}
        },
        "required": ["job_id", "target_url"]
    },
    handler=_audit_ai_visibility_tool
))

# ----------------- ACTIONS DOMAIN -----------------

async def _apply_approved_changes_tool(job_id: str) -> dict:
    from backend.routes.actions import apply_approved_changes
    try:
        await apply_approved_changes(job_id)
        return {"ok": True, "message": "Changes applied successfully."}
    except Exception as e:
        logger.error("apply_approved_changes_tool error: %s", e)
        return {"ok": False, "error": str(e)}

registry.register(ToolSpec(
    name="apply_approved_changes",
    description="Execute all user-approved SEO changes natively.",
    parameters={
        "type": "object",
        "properties": {
            "job_id": {"type": "string"}
        },
        "required": ["job_id"]
    },
    handler=_apply_approved_changes_tool,
    requires_checkpoint=True
))

async def _export_patch_tool(job_id: str, format: str = "json") -> dict:
    from backend.routes.actions import export_patch
    try:
        patch = await export_patch(job_id, format)
        return _compact({"ok": True, "patch": patch})
    except Exception as e:
        logger.error("export_patch_tool error: %s", e)
        return {"ok": False, "error": str(e)}

registry.register(ToolSpec(
    name="export_patch",
    description="Generate JSON or Markdown patches of reviewed actions.",
    parameters={
        "type": "object",
        "properties": {
            "job_id": {"type": "string"},
            "format": {"type": "string", "default": "json"}
        },
        "required": ["job_id"]
    },
    handler=_export_patch_tool
))

async def _github_pr_tool(job_id: str, domain: str, changes: list[dict], token: str | None = None) -> dict:
    from backend.services.notifications import create_github_pr
    try:
        pr_info = await create_github_pr(domain, changes, token)
        return {"ok": True, "pr_info": pr_info}
    except Exception as e:
        logger.error("github_pr_tool error: %s", e)
        return {"ok": False, "error": str(e)}

registry.register(ToolSpec(
    name="github_pr",
    description="Automatically file a GitHub pull request with the approved SEO changes.",
    parameters={
        "type": "object",
        "properties": {
            "job_id": {"type": "string"},
            "domain": {"type": "string"},
            "changes": {"type": "array", "items": {"type": "object"}},
            "token": {"type": "string"}
        },
        "required": ["job_id", "domain", "changes"]
    },
    handler=_github_pr_tool,
    requires_checkpoint=True
))

# ----------------- REPORTS DOMAIN -----------------

async def _generate_pdf_report_tool(job_id: str) -> dict:
    from backend.routes.reports import download_report_pdf
    try:
        # Note: download_report_pdf returns a StreamingResponse or Response from fastapi
        # The agent probably just needs to trigger generation or know it succeeded.
        # We'll just call it and return success if it doesn't throw.
        # However, FastAPI's download_report_pdf returns a Response object containing the bytes.
        res = await download_report_pdf(job_id)
        if getattr(res, "status_code", 200) >= 400:
            return {"ok": False, "error": f"Failed to generate PDF, status {getattr(res, 'status_code')}"}
        return {"ok": True, "message": "PDF report generated successfully."}
    except Exception as e:
        logger.error("generate_pdf_report_tool error: %s", e)
        return {"ok": False, "error": str(e)}

registry.register(ToolSpec(
    name="generate_pdf_report",
    description="Compile SEO findings into a branded PDF report.",
    parameters={
        "type": "object",
        "properties": {
            "job_id": {"type": "string"}
        },
        "required": ["job_id"]
    },
    handler=_generate_pdf_report_tool
))

async def _send_report_email_tool(job_id: str, to: str) -> dict:
    from backend.services.notifications import email_report
    try:
        sent, error = await email_report(job_id, to)
        if not sent:
            return {"ok": False, "error": error}
        return {"ok": True, "message": f"Email report sent to {to}."}
    except Exception as e:
        logger.error("send_report_email_tool error: %s", e)
        return {"ok": False, "error": str(e)}

registry.register(ToolSpec(
    name="send_report_email",
    description="Distribute the generated PDF report to stakeholders via email.",
    parameters={
        "type": "object",
        "properties": {
            "job_id": {"type": "string"},
            "to": {"type": "string"}
        },
        "required": ["job_id", "to"]
    },
    handler=_send_report_email_tool,
    requires_checkpoint=True
))

# ----------------- SCHEDULING DOMAIN -----------------

async def _create_schedule_tool(job_id: str, url: str, interval_hours: float, max_pages: int = 50, kind: str = "crawl") -> dict:
    from backend.routes.scheduler import create, CreateScheduleRequest
    try:
        req = CreateScheduleRequest(url=url, interval_hours=interval_hours, max_pages=max_pages, kind=kind)
        res = await create(req)
        return {"ok": True, "schedule_id": res.get("id")}
    except Exception as e:
        logger.error("create_schedule_tool error: %s", e)
        return {"ok": False, "error": str(e)}

registry.register(ToolSpec(
    name="create_schedule",
    description="Set up recurring automated crawls/analysis on a schedule.",
    parameters={
        "type": "object",
        "properties": {
            "job_id": {"type": "string"},
            "url": {"type": "string"},
            "interval_hours": {"type": "number"},
            "max_pages": {"type": "integer", "default": 50},
            "kind": {"type": "string", "default": "crawl"}
        },
        "required": ["job_id", "url", "interval_hours"]
    },
    handler=_create_schedule_tool
))

async def _list_schedules_tool(job_id: str) -> dict:
    from backend.routes.scheduler import list_all
    try:
        schedules = await list_all()
        # Filter schedules by URL or job? Actually list_all returns all schedules.
        # But we can compact it.
        return _compact({"ok": True, "schedules": schedules})
    except Exception as e:
        logger.error("list_schedules_tool error: %s", e)
        return {"ok": False, "error": str(e)}

registry.register(ToolSpec(
    name="list_schedules",
    description="List all currently active cron schedules for recurring analysis.",
    parameters={
        "type": "object",
        "properties": {
            "job_id": {"type": "string"}
        },
        "required": ["job_id"]
    },
    handler=_list_schedules_tool
))


# ----------------- COORDINATOR DOMAIN -----------------

async def _delegate_to_domain_agent(job_id: str, agent_domain: str, goal: str, urls: list[str], scope: str = "single_page") -> dict:
    from backend.services.agent_swarm import get_agent_for_domain
    from backend.models.agent_schemas import AgentRun
    from backend.db.mongo import get_db
    import uuid
    
    agent_cls = get_agent_for_domain(agent_domain)
    if not agent_cls:
        return {"ok": False, "error": f"Unknown agent domain: {agent_domain}"}
    
    def _domain(url: str) -> str:
        if "//" in url:
            return url.split("//")[-1].split("/")[0].lower()
        return url
    
    sub_run_id = str(uuid.uuid4())
    sub_run = AgentRun(
        id=sub_run_id,
        goal=goal,
        domain=_domain(urls[0]) if urls else "",
        agent_type=agent_domain,
        job_id=job_id,
        scope=scope,
        urls=urls,
        budget_credits=100.0,
        max_steps=15,
        checkpoint_policy="never",  # prevent sub-agents from blocking the coordinator indefinitely
        status="queued"
    )
    
    db = get_db()
    await db.agent_runs.insert_one(sub_run.model_dump())
    
    try:
        agent_instance = agent_cls(job_id=job_id)
        await agent_instance.start(sub_run_id)
        
        # Read the completed run
        completed_run = await db.agent_runs.find_one({"id": sub_run_id})
        if not completed_run:
            return {"ok": False, "error": "Sub-run not found after execution"}
            
        return {
            "ok": True,
            "sub_run_id": sub_run_id,
            "status": completed_run.get("status"),
            "facts": completed_run.get("facts", {}),
            "error": completed_run.get("error")
        }
    except Exception as e:
        logger.error("Delegate to %s failed: %s", agent_domain, e)
        return {"ok": False, "error": str(e)}

registry.register(ToolSpec(
    name="delegate_to_domain_agent",
    description="Delegate a sub-goal to a specific domain agent (e.g., 'crawl', 'analysis', 'competitor', 'technical', 'action', 'report', 'schedule').",
    parameters={
        "type": "object",
        "properties": {
            "job_id": {"type": "string"},
            "agent_domain": {"type": "string"},
            "goal": {"type": "string"},
            "urls": {"type": "array", "items": {"type": "string"}},
            "scope": {"type": "string", "default": "single_page"}
        },
        "required": ["job_id", "agent_domain", "goal", "urls"]
    },
    handler=_delegate_to_domain_agent
))

# ----------------- MEMORY DOMAIN -----------------

async def _store_memory_tool(job_id: str, domain: str, memory_type: str, key: str, value: str) -> dict:
    from backend.services.agent_memory import record_fact
    try:
        fact_key = f"{memory_type}:{key}"
        await record_fact(domain, fact_key, value)
        return {"ok": True, "message": f"Stored memory: {fact_key}"}
    except Exception as e:
        logger.error("store_memory_tool error: %s", e)
        return {"ok": False, "error": str(e)}

registry.register(ToolSpec(
    name="store_memory",
    description="Store persistent cross-session memory such as 'user_preference', 'domain_learning', or 'approval_pattern'.",
    parameters={
        "type": "object",
        "properties": {
            "job_id": {"type": "string"},
            "domain": {"type": "string", "description": "Use 'GLOBAL' for user preferences/patterns, or a specific domain for domain learnings"},
            "memory_type": {"type": "string", "enum": ["user_preference", "domain_learning", "approval_pattern"]},
            "key": {"type": "string"},
            "value": {"type": "string"}
        },
        "required": ["job_id", "domain", "memory_type", "key", "value"]
    },
    handler=_store_memory_tool
))


# --- LEGACY SANDBOX TOOLS (MIGRATED) ---

FIELD_MAP = {"title": "title_tag", "meta_description": "meta_description", "h1": "h1"}

SUPPORTED_FIELDS = ("title", "meta_description", "h1")

MAX_RESULT_CHARS = 6000


def _compact(value: Any, budget: int = MAX_RESULT_CHARS) -> Any:
    """Recursively trim a result to a fixed character budget."""
    text = json.dumps(value, default=str, ensure_ascii=False)
    if len(text) <= budget:
        return value
    try:
        return json.loads(text[:budget])
    except Exception:
        return {"truncated": text[: budget // 2]}


async def _page_facts(job_id: str, limit: int = 5) -> list[dict]:
    db = get_db()
    cursor = db.pages.find({"job_id": job_id}).sort("click_depth", 1).limit(limit)
    pages = await cursor.to_list(length=limit)
    facts = []
    for p in pages:
        facts.append(
            {
                "url": p.get("url", ""),
                "title": (p.get("title") or "")[:120],
                "title_length": len(p.get("title") or ""),
                "meta_description_present": bool(p.get("meta_description")),
                "meta_description_length": len(p.get("meta_description") or ""),
                "h1_count": p.get("h1_count", 0),
                "word_count": p.get("word_count", 0),
                "image_count": p.get("image_count", 0),
                "images_missing_alt": p.get("images_missing_alt", 0),
                "has_structured_data": p.get("has_structured_data", False),
                "is_indexable": p.get("is_indexable", True),
                "status_code": p.get("status_code"),
            }
        )
    return facts


async def _crawl_urls_tool(job_id: str, urls: list[str], max_pages: int = 1, mobile: bool = True) -> dict:
    if not urls:
        return {"ok": False, "error": "no urls provided"}
    url = urls[0]
    from backend.services.crawler import crawl_site

    summary = await crawl_site(
        job_id,
        url,
        max_pages=max_pages,
        seed_sitemap=False,
        unlimited=False,
        mobile=mobile,
    )
    facts = await _page_facts(job_id, limit=5)
    return {"ok": True, "target_url": url, "summary": summary, "page_facts": facts}


async def _run_analyzers_tool(job_id: str, analyzers: list[str] | None = None) -> dict:
    allowed = {"page_facts", "content", "links"}
    requested = {a for a in (analyzers or [])} & allowed
    if not requested:
        requested = {"page_facts"}
    out: dict[str, Any] = {"ok": True, "completed": sorted(requested)}
    db = get_db()
    if "page_facts" in requested:
        out["page_facts"] = await _page_facts(job_id, limit=5)
    if "content" in requested:
        breakdown = {}
        cursor = db.content_items.aggregate(
            [
                {"$match": {"job_id": job_id}},
                {"$group": {"_id": "$content_type", "n": {"$sum": 1}}},
            ]
        )
        async for row in cursor:
            breakdown[row["_id"]] = row["n"]
        out["content_breakdown"] = breakdown
    if "links" in requested:
        n = await db.link_health.count_documents({"job_id": job_id})
        out["link_rows"] = n
    return _compact(out)


async def _build_local_snapshot(page: dict) -> dict:
    """Snapshot dict (same shape as snapshot_service) built from a crawled page."""
    html = page.get("html") or ""
    soup = BeautifulSoup(html, "lxml")
    title = (soup.find("title").get_text(strip=True) if soup.find("title") else "") or ""
    h1 = soup.find("h1")
    h1_text = h1.get_text(strip=True) if h1 else ""
    meta_tags = []
    for m in soup.find_all("meta"):
        name = m.get("name") or m.get("property") or ""
        content = m.get("content") or ""
        if name:
            meta_tags.append({"name": name, "content": content})
    return {"dom": html, "meta_tags": meta_tags, "title": title, "h1": h1_text}


async def _draft_suggestions(pages: list[dict], focus_areas: list[str]) -> list[dict]:
    """LLM-draft improved title/meta/h1 per page. Returns raw draft rows."""
    areas = {a for a in (focus_areas or []) if a in {"meta", "headings"}}
    if not areas:
        areas = {"meta", "headings"}
    wants_title = "meta" in areas
    wants_meta = "meta" in areas
    wants_h1 = "headings" in areas

    if not settings.groq_api_key:
        return [
            {
                "url": p.get("url", ""),
                "title": None,
                "meta_description": None,
                "h1": None,
                "rationale": "No Groq key configured; deterministic draft only.",
            }
            for p in pages
        ]

    from groq import AsyncGroq

    client = AsyncGroq(api_key=settings.groq_api_key)
    rows = []
    for p in pages[:3]:
        prompt = (
            "You are an SEO copywriter. Improve ONLY these fields for the page below. "
            "Return JSON with keys: title, meta_description, h1, rationale.\n"
            f"URL: {p.get('url')}\n"
            f"Current title: {p.get('title') or ''}\n"
            f"Current meta description: {p.get('meta_description') or ''}\n"
            f"Current H1: {p.get('h1') or ''}\n"
            f"Word count: {p.get('word_count', 0)}\n"
            f"Constraints: title under 60 chars, meta description 140-160 chars, "
            f"one H1 under 70 chars, no ranking-position claims, no clickbait, "
            "keep field empty string ('') if it is already good."
        )
        try:
            completion = await client.chat.completions.create(
                model=settings.groq_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.4,
                max_tokens=2048,
                response_format={"type": "json_object"},
            )
            draft = json.loads(completion.choices[0].message.content or "{}")
        except Exception as e:
            logger.warning("Suggestion drafting failed for %s: %s", p.get("url"), e)
            draft = {}
        rows.append(
            {
                "url": p.get("url", ""),
                "title": draft.get("title") or None,
                "meta_description": draft.get("meta_description") or None,
                "h1": draft.get("h1") or None,
                "rationale": draft.get("rationale") or "Drafted by LLM from on-page signals.",
            }
        )
    return rows


async def _generate_suggestions_tool(job_id: str, focus_areas: list[str] | None = None) -> dict:
    db = get_db()
    cursor = db.pages.find({"job_id": job_id}).sort("click_depth", 1).limit(3)
    pages = await cursor.to_list(length=3)
    if not pages:
        return {"ok": False, "error": "no pages crawled for this job"}

    from backend.models.schemas import SeoSuggestion
    from backend.services.suggestion_validator import validate_suggestion

    drafts = await _draft_suggestions(pages, focus_areas or [])
    snapshots = {p.get("url"): await _build_local_snapshot(p) for p in pages}

    created = []
    for draft in drafts:
        url = draft["url"]
        page = next((p for p in pages if p.get("url") == url), None)
        snapshot = snapshots.get(url)
        if not page or not snapshot:
            continue
        candidates = []
        if draft.get("title") and page.get("title") != draft["title"]:
            candidates.append(
                ("title", page.get("title") or "", draft["title"])
            )
        if draft.get("meta_description") and (page.get("meta_description") or "") != draft["meta_description"]:
            candidates.append(
                ("meta_description", page.get("meta_description") or "", draft["meta_description"])
            )
        if draft.get("h1"):
            h1_text = snapshot["h1"]
            if h1_text != draft["h1"]:
                candidates.append(("h1", h1_text, draft["h1"]))
        for field_type, current, suggested in candidates:
            evidence = current or (snapshot.get("title") or url[:80])
            sug = SeoSuggestion(
                id=str(uuid.uuid4()),
                page_url=url,
                field_type=field_type,
                current_value=current,
                suggested_value=suggested,
                rationale=draft["rationale"],
                evidence_source=evidence,
                status="pending",
            )
            if not validate_suggestion(sug, snapshot):
                logger.info("Agent suggestion rejected by validator: %s %s", url, field_type)
                continue
            doc = sug.model_dump()
            doc["job_id"] = job_id
            await db.sandbox_suggestions.insert_one(doc)
            created.append(
                {
                    "id": sug.id,
                    "page_url": url,
                    "field_type": field_type,
                    "current_value": current[:80],
                    "suggested_value": suggested[:120],
                    "rationale": draft["rationale"][:160],
                }
            )

    return {"ok": True, "created": created, "count": len(created)}


async def _apply_changes_tool(job_id: str, suggestion_ids: list[str]) -> dict:
    from backend.services.snapshot_service import capture_snapshot
    from backend.services.notifications import create_github_pr
    from urllib.parse import urlparse

    db = get_db()
    applied = []
    failed = []

    # Group suggestions by page_url
    suggestions_by_url = {}
    for sid in suggestion_ids or []:
        doc = await db.sandbox_suggestions.find_one({"id": sid})
        if not doc:
            failed.append({"id": sid, "error": "suggestion not found"})
            continue
        page_url = doc.get("page_url")
        if not page_url:
            failed.append({"id": sid, "error": "no page_url"})
            continue
        suggestions_by_url.setdefault(page_url, []).append(doc)

    preview_urls = []
    
    for page_url, docs in suggestions_by_url.items():
        domain = urlparse(page_url).netloc
        
        # 1. Take a live visual snapshot with changes
        try:
            await capture_snapshot(page_url, job_id=job_id, tag=f"apply_{job_id}", changes=docs)
        except Exception as e:
            logger.warning("Visual snapshot capture failed for %s: %s", page_url, e)
            
        # 2. Create GitHub PR for these changes
        pr_result = await create_github_pr(domain, docs)
        
        if pr_result and pr_result.get("ok"):
            preview_url = pr_result.get("html_url")
            preview_urls.append(preview_url)
            for doc in docs:
                sid = doc["id"]
                await db.sandbox_suggestions.update_one(
                    {"id": sid}, 
                    {"$set": {"status": "applied", "last_commit_hash": "github_pr"}}
                )
                applied.append({
                    "id": sid,
                    "page_url": page_url,
                    "field_type": doc.get("field_type"),
                    "preview_url": preview_url,
                })
        else:
            msg = pr_result.get("error") if pr_result else "No GitHub token configured"
            for doc in docs:
                failed.append({"id": doc["id"], "error": msg})

    return {"ok": True, "applied": applied, "failed": failed, "preview_urls": preview_urls}


async def _read_current_state_tool(job_id: str) -> dict:
    db = get_db()
    facts = await db.agent_facts.find_one({"job_id": job_id})
    if facts and "_id" in facts:
        del facts["_id"]
    return {"status": "ok", "facts": facts or {}}


async def _query_knowledge_tool(job_id: str, domain: str, question: str) -> dict:
    from backend.services.agent_memory import get_domain_facts
    facts = await get_domain_facts(domain)
    return {
        "domain": domain,
        "facts_summary": facts.get("insights", {}),
        "recent_episodes": facts.get("episodes", [])[-3:]
    }


FIELD_MAP = {
    "title": "title_tag",
    "meta_description": "meta_description",
    "h1": "h1",
    "h2": "h2",
    "canonical": "canonical",
    "robots": "meta_robots",
    "schema": "schema_jsonld",
}


TOOL_REGISTRY: dict[str, dict] = {
    "crawl_urls": {
        "name": "crawl_urls",
        "description": "Crawl a list of URLs (single-page scope: exactly one URL, max_pages=1). Returns crawl summary and per-page SEO facts.",
        "parameters": {
            "type": "object",
            "properties": {
                "urls": {"type": "array", "items": {"type": "string"}},
                "max_pages": {"type": "integer", "default": 1},
                "mobile": {"type": "boolean", "default": True},
            },
            "required": ["urls"],
        },
        "handler": _crawl_urls_tool,
        "requires_checkpoint": False,
        "credit_cost": 0.0,
    },
    "run_analyzers": {
        "name": "run_analyzers",
        "description": "Run local analyzers over crawled pages. Analyzers: page_facts, content, links.",
        "parameters": {
            "type": "object",
            "properties": {
                "analyzers": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["analyzers"],
        },
        "handler": _run_analyzers_tool,
        "requires_checkpoint": False,
        "credit_cost": 0.0,
    },
    "generate_suggestions": {
        "name": "generate_suggestions",
        "description": "Draft improved title/meta-description/h1 suggestions from crawled pages, validate evidence, and store them in sandbox_suggestions (status pending). Focus areas: meta, headings.",
        "parameters": {
            "type": "object",
            "properties": {
                "focus_areas": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["focus_areas"],
        },
        "handler": _generate_suggestions_tool,
        "requires_checkpoint": False,
        "credit_cost": 0.0,
    },
    "apply_changes": {
        "name": "apply_changes",
        "description": "Apply approved suggestions by creating a GitHub Pull Request and capturing a visual live preview. Requires human approval.",
        "parameters": {
            "type": "object",
            "properties": {
                "suggestion_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["suggestion_ids"],
        },
        "handler": _apply_changes_tool,
        "requires_checkpoint": True,
        "credit_cost": 0.0,
    },
    "read_current_state": {
        "name": "read_current_state",
        "description": "Read the current crawl/analysis/suggestion state for the job without side effects.",
        "parameters": {"type": "object", "properties": {}},
        "handler": _read_current_state_tool,
        "requires_checkpoint": False,
        "credit_cost": 0.0,
    },
    "query_knowledge": {
        "name": "query_knowledge",
        "description": "Query durable domain facts and recent agent episodes (cross-run memory).",
        "parameters": {
            "type": "object",
            "properties": {
                "domain": {"type": "string"},
                "question": {"type": "string"},
            },
            "required": ["domain"],
        },
        "handler": _query_knowledge_tool,
        "requires_checkpoint": False,
        "credit_cost": 0.0,
    },
}


for name, tool_dict in TOOL_REGISTRY.items():
    registry.register(ToolSpec(
        name=tool_dict["name"],
        description=tool_dict["description"],
        parameters=tool_dict["parameters"],
        handler=tool_dict["handler"],
        requires_checkpoint=tool_dict.get("requires_checkpoint", False),
        credit_cost=tool_dict.get("credit_cost", 0.0)
    ))
