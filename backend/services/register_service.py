from typing import List, Dict, Any
from datetime import datetime, timedelta
from backend.db.mongo import get_db
from backend.models.register_schemas import SeoTaskDef, Cadence, Pillar, Mode, SourceId, ScheduleHint, RunStatus, TaskRun, SiteTaskConfig

TASK_SEED = [
    # Weekly
    SeoTaskDef(id="W1", cadence=Cadence.weekly, pillar=Pillar.onpage, title="Search performance pulse", commitment="clicks, impressions, CTR, position week-over-week; top gainers/losers", howItRuns="Snapshot stored; movers beyond threshold flagged. Note GSC lag", mode=Mode.auto, sources=[SourceId.gsc], doneWhen="Snapshot stored; movers beyond threshold flagged.", scheduleHint=ScheduleHint()),
    SeoTaskDef(id="W2", cadence=Cadence.weekly, pillar=Pillar.technical, title="Indexation watch", commitment="sitemap status, submitted vs indexed, URL Inspection sample", howItRuns="Sample inspected; non-indexed priority URLs listed", mode=Mode.auto, sources=[SourceId.gsc], doneWhen="Sample inspected; non-indexed priority URLs listed", scheduleHint=ScheduleHint()),
    SeoTaskDef(id="W3", cadence=Cadence.weekly, pillar=Pillar.technical, title="Crawl-health delta on priority URLs", commitment="new 4xx/5xx, redirect chains, noindex / canonical changes", howItRuns="Diff vs previous run stored; regressions flagged", mode=Mode.auto, sources=[SourceId.crawl], doneWhen="Diff vs previous run stored; regressions flagged", scheduleHint=ScheduleHint()),
    SeoTaskDef(id="W4", cadence=Cadence.weekly, pillar=Pillar.technical, title="Core Web Vitals regression check", commitment="check on key templates", howItRuns="Compared with baseline; regressions flagged", mode=Mode.auto, sources=[SourceId.lighthouse, SourceId.crux], doneWhen="Compared with baseline; regressions flagged", scheduleHint=ScheduleHint()),
    SeoTaskDef(id="W5", cadence=Cadence.weekly, pillar=Pillar.offpage, title="Priority-keyword SERP snapshot", commitment="competitor positions, SERP features", howItRuns="Snapshot stored — builds the history monthly analysis needs", mode=Mode.auto, sources=[SourceId.serp_snapshot], doneWhen="Snapshot stored", scheduleHint=ScheduleHint()),
    SeoTaskDef(id="W6", cadence=Cadence.weekly, pillar=Pillar.onpage, title="New/changed page QA", commitment="every page published or edited this week passes checks", howItRuns="Checked-URL list stored; failures queued", mode=Mode.auto, sources=[SourceId.crawl], doneWhen="Checked-URL list stored", scheduleHint=ScheduleHint()),
    SeoTaskDef(id="W7", cadence=Cadence.weekly, pillar=Pillar.onpage, title="Editorial pipeline check", commitment="was this week's article slot published?", howItRuns="Slot marked published / slipped with reason", mode=Mode.manual, sources=[SourceId.manual], doneWhen="Slot marked published / slipped with reason", scheduleHint=ScheduleHint()),
    SeoTaskDef(id="W8", cadence=Cadence.weekly, pillar=Pillar.offpage, title="Brand mention & review alert digest", commitment="logged even when empty", howItRuns="Digest line logged", mode=Mode.manual, sources=[SourceId.manual], doneWhen="Digest line logged", scheduleHint=ScheduleHint()),

    # Monthly
    SeoTaskDef(id="M1", cadence=Cadence.monthly, pillar=Pillar.technical, title="Full-site technical crawl and audit", commitment="findings logged by severity, compared to baseline", howItRuns="Audit stored; findings vs baseline computed", mode=Mode.auto, sources=[SourceId.crawl], doneWhen="Audit stored; findings vs baseline computed", scheduleHint=ScheduleHint(week=1)),
    SeoTaskDef(id="M2", cadence=Cadence.monthly, pillar=Pillar.technical, title="Crawl-error resolution", commitment="4xx, redirect chains, orphan pages, index errors — fixed", howItRuns="Queue items fixed or accepted", mode=Mode.assisted, sources=[SourceId.crawl, SourceId.gsc], doneWhen="Queue items fixed or accepted-with-reason", scheduleHint=ScheduleHint(week=2)),
    SeoTaskDef(id="M3", cadence=Cadence.monthly, pillar=Pillar.technical, title="Core Web Vitals monthly review", commitment="regressions diagnosed and repaired", howItRuns="Trend stored; each regression has a diagnosis and an owner", mode=Mode.assisted, sources=[SourceId.lighthouse, SourceId.crux], doneWhen="Trend stored; regressions diagnosed", scheduleHint=ScheduleHint(week=1)),
    SeoTaskDef(id="M4", cadence=Cadence.monthly, pillar=Pillar.technical, title="Structured data validation", commitment="template-level schema grading + Rich Results spot-check", howItRuns="Zero new schema errors, or logged", mode=Mode.assisted, sources=[SourceId.crawl, SourceId.manual], doneWhen="Zero new schema errors, or logged; spot-check URLs recorded", scheduleHint=ScheduleHint(week=3)),
    SeoTaskDef(id="M5", cadence=Cadence.monthly, pillar=Pillar.technical, title="Sitemap & robots hygiene", commitment="reconcile sitemap vs crawl vs indexed", howItRuns="Reconciliation diff stored", mode=Mode.auto, sources=[SourceId.crawl, SourceId.gsc], doneWhen="Reconciliation diff stored", scheduleHint=ScheduleHint(week=1)),
    SeoTaskDef(id="M6", cadence=Cadence.monthly, pillar=Pillar.technical, title="Image SEO pass", commitment="alt-text coverage, filenames, weight", howItRuns="Coverage % stored vs previous month", mode=Mode.assisted, sources=[SourceId.crawl], doneWhen="Coverage % stored vs previous month", scheduleHint=ScheduleHint(week=2)),
    SeoTaskDef(id="M7", cadence=Cadence.monthly, pillar=Pillar.technical, title="AEO / GEO visibility panel", commitment="a fixed set of buyer questions put to AI assistants", howItRuns="Panel results stored", mode=Mode.assisted, sources=[SourceId.manual], doneWhen="Panel results stored so the report carries a trend", scheduleHint=ScheduleHint(week=3)),
    SeoTaskDef(id="M8", cadence=Cadence.monthly, pillar=Pillar.onpage, title="Keyword & ranking review", commitment="priority terms, underperformers, striking distance", howItRuns="Review list stored", mode=Mode.auto, sources=[SourceId.gsc], doneWhen="Review list stored; underperformers routed to M9", scheduleHint=ScheduleHint(week=2)),
    SeoTaskDef(id="M9", cadence=Cadence.monthly, pillar=Pillar.onpage, title="Meta-tag optimisation cycle", commitment="draft → verify → review queue → apply", howItRuns="Approved changes applied; before/after tracked", mode=Mode.assisted, sources=[SourceId.gsc, SourceId.crawl], doneWhen="Approved changes applied; before/after tracked", scheduleHint=ScheduleHint(week=2)),
    SeoTaskDef(id="M10", cadence=Cadence.monthly, pillar=Pillar.onpage, title="Content freshness sweep", commitment="stale pages ranked by age and traffic decay", howItRuns="reviewedOn updated on swept pages", mode=Mode.assisted, sources=[SourceId.crawl, SourceId.gsc], doneWhen="reviewedOn updated on swept pages", scheduleHint=ScheduleHint(week=3)),
    SeoTaskDef(id="M11", cadence=Cadence.monthly, pillar=Pillar.onpage, title="Search-growth content", commitment="publish planned articles; book next month's slots", howItRuns="Published count vs planned; next month slots booked", mode=Mode.manual, sources=[SourceId.manual], doneWhen="Published count vs planned; slots booked", scheduleHint=ScheduleHint(week=1)),
    SeoTaskDef(id="M12", cadence=Cadence.monthly, pillar=Pillar.onpage, title="Optimise new/updated pages", commitment="optimise pages received this month", howItRuns="Before/after comparison attached", mode=Mode.assisted, sources=[SourceId.manual], doneWhen="Before/after comparison attached", scheduleHint=ScheduleHint(week=3)),
    SeoTaskDef(id="M13", cadence=Cadence.monthly, pillar=Pillar.offpage, title="Citation & directory register", commitment="verify a slice, correct drift", howItRuns="Slice verified; corrections logged", mode=Mode.manual, sources=[SourceId.manual], doneWhen="Slice verified; corrections logged", scheduleHint=ScheduleHint(week=2)),
    SeoTaskDef(id="M14", cadence=Cadence.monthly, pillar=Pillar.offpage, title="Backlink review", commitment="new/lost links; reclamation list", howItRuns="Profile snapshot stored", mode=Mode.assisted, sources=[SourceId.manual, SourceId.firecrawl], doneWhen="Profile snapshot stored; reclamation list updated", scheduleHint=ScheduleHint(week=3)),
    SeoTaskDef(id="M15", cadence=Cadence.monthly, pillar=Pillar.offpage, title="Outreach batch", commitment="every send and reply logged", howItRuns="Batch logged", mode=Mode.manual, sources=[SourceId.manual], doneWhen="Batch logged", scheduleHint=ScheduleHint(week=3)),
    SeoTaskDef(id="M16", cadence=Cadence.monthly, pillar=Pillar.offpage, title="Competitor tracking", commitment="rankings, keywords, authority proxy, content velocity", howItRuns="Competitor data stored", mode=Mode.auto, sources=[SourceId.serp_snapshot, SourceId.crawl], doneWhen="Competitor data stored", scheduleHint=ScheduleHint(week=4)),
    SeoTaskDef(id="M17", cadence=Cadence.monthly, pillar=Pillar.offpage, title="Brand & reputation watch", commitment="monthly line in the report", howItRuns="Line logged, including nothing found", mode=Mode.manual, sources=[SourceId.manual], doneWhen="Line logged", scheduleHint=ScheduleHint(week=4)),
    SeoTaskDef(id="M18", cadence=Cadence.monthly, pillar=Pillar.reporting, title="Monthly SEO Report", commitment="assembled, validated, issued; next month's plan agreed", howItRuns="Immutable ReportSnapshot issued", mode=Mode.auto, sources=[SourceId.gsc, SourceId.crawl, SourceId.ga4, SourceId.manual, SourceId.serp_snapshot], doneWhen="Immutable ReportSnapshot issued", scheduleHint=ScheduleHint(week=4), dependsOn=["M1", "M8", "M16"]),

    # Quarterly
    SeoTaskDef(id="Q1", cadence=Cadence.quarterly, pillar=Pillar.reporting, title="Quarterly strategy review", commitment="performance vs goals; next-quarter roadmap", howItRuns="Quarterly report issued", mode=Mode.assisted, sources=[SourceId.manual], doneWhen="Quarterly report issued; roadmap accepted", scheduleHint=ScheduleHint()),
    SeoTaskDef(id="Q2", cadence=Cadence.quarterly, pillar=Pillar.onpage, title="Keyword research refresh", commitment="keyword-map rebuild", howItRuns="New keyword map stored", mode=Mode.assisted, sources=[SourceId.keyword_planner, SourceId.gsc, SourceId.manual], doneWhen="New keyword map stored; changes listed", scheduleHint=ScheduleHint()),
    SeoTaskDef(id="Q3", cadence=Cadence.quarterly, pillar=Pillar.onpage, title="Content inventory audit", commitment="keep/improve/merge/redirect/remove decisions", howItRuns="Decisions recorded and queued", mode=Mode.assisted, sources=[SourceId.crawl, SourceId.gsc, SourceId.ga4], doneWhen="Decisions recorded and queued", scheduleHint=ScheduleHint()),
    SeoTaskDef(id="Q4", cadence=Cadence.quarterly, pillar=Pillar.technical, title="Site architecture & internal-linking review", commitment="click depth, hubs, topical clusters", howItRuns="Findings and link-change queue stored", mode=Mode.assisted, sources=[SourceId.crawl], doneWhen="Findings and link-change queue stored", scheduleHint=ScheduleHint()),
    SeoTaskDef(id="Q5", cadence=Cadence.quarterly, pillar=Pillar.offpage, title="Competitive gap analysis", commitment="keyword, content, SERP-feature and authority gaps", howItRuns="Gap list stored", mode=Mode.assisted, sources=[SourceId.serp_snapshot, SourceId.crawl], doneWhen="Gap list stored, ranked by opportunity", scheduleHint=ScheduleHint()),
    SeoTaskDef(id="Q6", cadence=Cadence.quarterly, pillar=Pillar.offpage, title="Backlink deep audit", commitment="link-gap vs competitors; clean-up decisions", howItRuns="Audit stored; actions logged", mode=Mode.manual, sources=[SourceId.manual, SourceId.firecrawl], doneWhen="Audit stored; actions logged", scheduleHint=ScheduleHint()),
    SeoTaskDef(id="Q7", cadence=Cadence.quarterly, pillar=Pillar.reporting, title="Algorithm & guideline impact review", commitment="core updates and Google guideline changes", howItRuns="Review note stored", mode=Mode.manual, sources=[SourceId.gsc, SourceId.ga4], doneWhen="Review note stored; follow-up tasks created", scheduleHint=ScheduleHint()),
    SeoTaskDef(id="Q8", cadence=Cadence.quarterly, pillar=Pillar.technical, title="AEO / GEO strategy review", commitment="refresh the prompt panel, quarter trend", howItRuns="Updated panel and trend stored", mode=Mode.assisted, sources=[SourceId.manual], doneWhen="Updated panel and trend stored", scheduleHint=ScheduleHint()),
    SeoTaskDef(id="Q9", cadence=Cadence.quarterly, pillar=Pillar.reporting, title="Measurement integrity audit", commitment="GA4 key events, GSC–GA4 link, property settings", howItRuns="Checklist completed", mode=Mode.manual, sources=[SourceId.ga4, SourceId.gsc], doneWhen="Checklist completed with results", scheduleHint=ScheduleHint()),
    SeoTaskDef(id="Q10", cadence=Cadence.quarterly, pillar=Pillar.technical, title="Deep technical audit", commitment="JS-rendered vs raw crawl comparison, mobile, hreflang", howItRuns="Audit stored", mode=Mode.assisted, sources=[SourceId.crawl], doneWhen="Audit stored; inapplicable parts marked n/a", scheduleHint=ScheduleHint()),
    SeoTaskDef(id="Q11", cadence=Cadence.quarterly, pillar=Pillar.offpage, title="Local SEO / Business Profile audit", commitment="audit if site has local intent", howItRuns="Audit stored, or disabled with reason", mode=Mode.manual, sources=[SourceId.manual], doneWhen="Audit stored, or task disabled with reason", scheduleHint=ScheduleHint()),
]

def get_all_task_defs() -> List[SeoTaskDef]:
    return TASK_SEED

async def get_register_state(site_id: str, period_key: str) -> Dict[str, Any]:
    db = get_db()
    
    # In Phase 2, we query all runs for this site
    cursor = db.task_runs.find({"siteId": site_id})
    all_runs = await cursor.to_list(length=None)
    
    # Filter runs to current period for derived state
    period_runs = {run["taskId"]: run for run in all_runs if run["periodKey"] == period_key}
    
    # Fetch task configs for this site
    configs_cursor = db.site_task_configs.find({"siteId": site_id})
    configs = await configs_cursor.to_list(length=None)
    config_map = {c["taskId"]: c for c in configs}
    
    tasks = [t.model_dump() for t in TASK_SEED]
    
    for t in tasks:
        c = config_map.get(t["id"])
        if c:
            t["enabled"] = c.get("enabled", True)
            t["disabledReason"] = c.get("disabledReason")
        else:
            t["enabled"] = True
            t["disabledReason"] = None
    
    # Capability tally
    capability = {"auto": 0, "assisted": 0, "manual": 0}
    for t in tasks:
        # Only tally enabled tasks for capability?
        # Let's count all or just enabled. Spec implies true capability. Let's count all enabled.
        if t["enabled"]:
            capability[t["mode"]] += 1
        
    period = {"done": 0, "due": 0, "overdue": 0, "blocked": 0, "skipped": 0, "n/a": 0}
    
    now = datetime.now()
    
    for t in tasks:
        # Evaluate derived state
        run = period_runs.get(t["id"])
        
        if not t["enabled"]:
            state = "n/a"
        elif run:
            status = run.get("status")
            if status == "done":
                state = "done"
            elif status in ["skipped", "failed"]:
                state = "blocked" if status == "failed" else "skipped"
            else:
                state = "due"
        else:
            # Check deadline
            is_overdue = False
            
            # Simple heuristic for mock
            if t["cadence"] == "weekly":
                # Weekly tasks are due by end of the week. For simplicity, just due.
                is_overdue = False 
            elif t["cadence"] == "monthly":
                week = t["scheduleHint"].get("week")
                if week:
                    deadline_day = week * 7
                    if now.day > deadline_day:
                        is_overdue = True
            
            state = "overdue" if is_overdue else "due"
            
        t["derivedState"] = state
        
        # Accumulate period
        if state in period:
            period[state] += 1
        else:
            period["due"] += 1
            
    return {
        "siteId": site_id,
        "periodKey": period_key,
        "tallies": {
            "capability": capability,
            "period": period
        },
        "tasks": tasks,
        "gaps": []
    }
