"""Site-level health score computed from crawl + link-check data.

The score is a transparent roll-up of *measured* component values:

* every component is a 0-100 pass-rate computed from crawl data (e.g. "% of pages with an H1");
* a category's score is the mean of its measured components;
* the overall score is the weight-averaged mean of the *measured* categories - a category with
  no data is left out (and listed in ``unmeasured_categories``); it is never scored as 100;
* ``score_breakdown`` lists every component so the number can be reproduced by hand.

The category weights below are a published policy choice (how much each area matters), not data.
"""

from datetime import datetime

from backend.db.mongo import get_db
from backend.services.seo_rules import DEEP_CLICK_DEPTH, LONG_REDIRECT_CHAIN, is_error_page, is_thin

SCORE_WEIGHTS = {
    "technical": 25, "performance": 20, "on_page": 15, "content": 15,
    "mobile": 10, "links": 5, "security": 5, "schema_a11y": 5,
}


def _grade(score) -> str:
    if score is None:
        return "N/A"
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


def _pct_ok(bad, total):
    """Share (0-100) of items that are NOT bad; None when nothing could be evaluated."""
    return None if not total else round(100 * (1 - min(bad, total) / total), 1)


def compute_score(m: dict) -> dict:
    """Pure roll-up of already-computed metrics (see module docstring)."""
    n = m.get("pages_analyzed") or 0
    crawled = m.get("pages_crawled") or 0
    rate = m.get("broken_link_rate")
    thin_eval = m.get("pages_evaluated_word_count") or 0
    comps = {
        "technical": [
            ("link_health", None if rate is None else round(100 - rate, 1)),
            ("crawl_depth", _pct_ok(m.get("deep_click_depth_pages", 0), n)),
            ("redirect_chains", _pct_ok(m.get("long_redirect_chain_pages", 0), n)),
            ("http_errors", _pct_ok(m.get("error_pages", 0), crawled)),
        ],
        "performance": [("cwv_pass_rate", m.get("cwv_pass_rate"))],
        "on_page": [
            ("meta_description_coverage", m.get("meta_description_coverage")),
            ("h1_coverage", m.get("h1_coverage")),
            ("title_coverage", m.get("title_coverage")),
        ],
        "content": [
            ("not_thin", _pct_ok(m.get("thin_pages", 0), thin_eval)),
            ("not_duplicate", _pct_ok(m.get("duplicate_pages", 0), n) if "duplicate_pages" in m else None),
        ],
        "mobile": [("mobile_friendly", None if not m.get("mobile_friendly_evaluated") else round(100 * m.get("mobile_friendly_pages", 0) / m["mobile_friendly_evaluated"], 1))],
        "links": [("not_orphaned", _pct_ok(m.get("orphan_pages", 0), n) if "orphan_pages" in m else None)],
        "security": [("https_pages", None if not m.get("https_evaluated") else round(100 * m.get("https_entry_pages", 0) / m["https_evaluated"], 1))],
        "schema_a11y": [
            ("alt_text_coverage", m.get("alt_text_coverage")),
            ("structured_data_coverage", _pct_ok(m.get("structured_data_missing", 0), n) if "structured_data_missing" in m else None),
        ],
    }
    breakdown, num, den, unmeasured = [], 0.0, 0, []
    for cat, weight in SCORE_WEIGHTS.items():
        measured = [(name, v) for name, v in comps[cat] if v is not None]
        cat_score = round(sum(v for _, v in measured) / len(measured), 1) if measured else None
        breakdown.append({
            "category": cat, "weight": weight, "score": cat_score, "measured": cat_score is not None,
            "components": [{"name": name, "value": v} for name, v in comps[cat]],
        })
        if cat_score is None:
            unmeasured.append(cat)
        else:
            num += weight * cat_score
            den += weight
    score = round(num / den) if den else None
    return {
        "score": score,
        "grade": _grade(score),
        "score_breakdown": breakdown,
        "category_scores": {b["category"]: (None if b["score"] is None else round(b["score"])) for b in breakdown},
        "unmeasured_categories": unmeasured,
        "score_coverage_pct": den,  # weights are out of 100, so this is the % of the score backed by data
    }


async def compute_site_health(job_id: str) -> dict:
    db = get_db()
    all_pages = await db.pages.find({"job_id": job_id}, {"html": 0}).to_list(length=None)
    lh = await db.link_health_summaries.find_one({"job_id": job_id})
    issues: list[dict] = []
    metrics: dict = {}

    # Error responses (4xx/5xx) have no content: they are reported as errors and excluded from
    # content/coverage metrics instead of being scored as pages with no title, H1 or meta description.
    error_pages = [p for p in all_pages if is_error_page(p)]
    pages = [p for p in all_pages if not is_error_page(p)]
    n = len(pages)
    metrics["pages_analyzed"] = n
    metrics["pages_crawled"] = len(all_pages)
    metrics["error_pages"] = len(error_pages)
    if error_pages:
        worst = max((p.get("status_code") or 0) for p in error_pages)
        issues.append({"severity": "high" if worst >= 500 else "medium", "message": f"{len(error_pages)} crawled URL(s) returned HTTP errors (e.g. {error_pages[0].get('status_code')}): {error_pages[0].get('url')}"})

    # Link health
    lh_counts = (lh or {}).get("counts") or (lh or {})
    links_checked = lh_counts.get("checked", 0)
    broken = lh_counts.get("broken_link_count")
    legacy = False
    if broken is None:
        legacy = True
        broken = (
            lh_counts.get("broken", 0)
            + lh_counts.get("timeout", 0)
            + lh_counts.get("error", 0)
            + lh_counts.get("blocked", 0)
        )
    metrics["links_checked"] = links_checked
    metrics["broken_links"] = broken
    if legacy:
        metrics["broken_links_legacy_bucket"] = True
    metrics["broken_link_rate"] = round(100 * broken / links_checked, 1) if links_checked else None
    if metrics["broken_link_rate"] is not None:
        label = "broken or unreachable" if legacy else "broken"
        if metrics["broken_link_rate"] > 10:
            issues.append({"severity": "high", "message": f"{broken} of {links_checked} links are {label} ({metrics['broken_link_rate']}%)."})
        elif metrics["broken_link_rate"] > 2:
            issues.append({"severity": "medium", "message": f"{broken} {label} links found ({metrics['broken_link_rate']}%)."})

    if n:
        evaluated = lambda key: [p for p in pages if p.get(key) is not None]
        with_meta = sum(1 for p in pages if p.get("meta_description"))
        meta_evaluated = len(evaluated("meta_description"))
        with_h1 = sum(1 for p in pages if (p.get("h1_count") or 0) > 0)
        h1_evaluated = len(evaluated("h1_count"))
        indexable = sum(1 for p in pages if p.get("is_indexable", True))
        thin_pool = [p for p in pages if p.get("is_indexable", True) and p.get("word_count") is not None]
        thin = sum(1 for p in thin_pool if is_thin(p)[0])
        thin_evaluated = len(thin_pool)
        title_evaluated = len(evaluated("title"))
        with_title = sum(1 for p in pages if (p.get("title") or "").strip())
        metrics["title_coverage"] = round(100 * with_title / title_evaluated) if title_evaluated else None
        images_total = sum(p.get("image_count") or 0 for p in pages)
        images_missing_alt = sum(p.get("images_missing_alt") or 0 for p in pages)

        metrics["pages_with_meta_description"] = with_meta
        metrics["pages_evaluated_meta"] = meta_evaluated
        metrics["meta_description_coverage"] = round(100 * with_meta / meta_evaluated) if meta_evaluated else None
        metrics["pages_with_h1"] = with_h1
        metrics["pages_evaluated_h1"] = h1_evaluated
        metrics["h1_coverage"] = round(100 * with_h1 / h1_evaluated) if h1_evaluated else None
        metrics["indexable_pages"] = indexable
        metrics["indexable_rate"] = round(100 * indexable / n)
        metrics["thin_pages"] = thin
        metrics["pages_evaluated_word_count"] = thin_evaluated
        metrics["images_total"] = images_total
        metrics["images_missing_alt"] = images_missing_alt
        metrics["alt_text_coverage"] = round(100 * (images_total - images_missing_alt) / images_total) if images_total else None

        if metrics["alt_text_coverage"] is not None and metrics["alt_text_coverage"] < 60:
            issues.append({"severity": "high", "message": f"{images_missing_alt} of {images_total} images are missing alt text ({metrics['alt_text_coverage']}% coverage)."})
        elif metrics["alt_text_coverage"] is not None and metrics["alt_text_coverage"] < 90:
            issues.append({"severity": "medium", "message": f"{images_missing_alt} images are missing alt text."})
        if metrics["meta_description_coverage"] is not None and metrics["meta_description_coverage"] < 70:
            issues.append({"severity": "medium", "message": f"Only {metrics['meta_description_coverage']}% of pages have a meta description."})
        if metrics["h1_coverage"] is not None and metrics["h1_coverage"] < 80:
            issues.append({"severity": "medium", "message": f"Only {metrics['h1_coverage']}% of pages have an H1 heading."})
        if metrics["thin_pages"] > 0:
            issues.append({"severity": "medium", "message": f"{metrics['thin_pages']} indexable page(s) are below the minimum main-content word count for their page type (thin content)."})
        if metrics["title_coverage"] is not None and metrics["title_coverage"] < 100:
            issues.append({"severity": "high", "message": f"{title_evaluated - with_title} page(s) have no <title>."})
        if metrics["indexable_rate"] < 100:
            issues.append({"severity": "low", "message": f"{n - indexable} page(s) are blocked from indexing (noindex)."})

        from backend.services.performance_service import classify_metric

        perfs = await db.page_performance.find({"job_id": job_id}).to_list(length=None)
        mobile = {}
        for p in perfs:
            if (p.get("strategy") or "mobile") == "mobile":
                mobile.setdefault(p.get("url"), p)
        if mobile:
            verdicts = [(p.get("cwv_assessment") or {}).get("overall") for p in mobile.values()]
            passed, failed = verdicts.count("passed"), verdicts.count("failed")
            cwv_scores = [p["cwv_score"] for p in mobile.values() if p.get("cwv_score") is not None]
            metrics["cwv_pages_checked"] = len(mobile)
            metrics["cwv_pages_total"] = n  # the sample is a subset of the site; say so
            metrics["cwv_passed_pages"] = passed
            metrics["cwv_failed_pages"] = failed
            metrics["cwv_assessed_pages"] = passed + failed
            metrics["cwv_pass_rate"] = round(100 * passed / (passed + failed)) if passed + failed else None
            metrics["avg_cwv_score"] = round(sum(cwv_scores) / len(cwv_scores)) if cwv_scores else None
            for key, label in (("lcp", "poor_lcp_pages"), ("inp", "poor_inp_pages"), ("cls", "poor_cls_pages")):
                metrics[label] = sum(1 for p in mobile.values() if classify_metric(key, (p.get("cwv") or {}).get(key)) == "poor")
            if passed + failed == 0:
                issues.append({"severity": "low", "message": "No Core Web Vitals field data (CrUX) was available for the sampled pages, so only lab diagnostics exist and no pass/fail assessment was made."})
            elif failed:
                share = failed / (passed + failed)
                issues.append({"severity": "high" if share > 0.5 else "medium", "message": f"{failed} of {passed + failed} assessed page(s) fail Core Web Vitals (field data, sample of {len(mobile)} of {n} pages)."})

        https_pages = sum(1 for p in pages if p.get("https_entry"))
        metrics["https_entry_pages"] = https_pages
        metrics["https_evaluated"] = sum(1 for p in pages if p.get("https_entry") is not None)
        deep_count = sum(1 for p in pages if (p.get("click_depth") or 0) > DEEP_CLICK_DEPTH)
        metrics["deep_click_depth_pages"] = deep_count
        mobile_friendly = sum(1 for p in pages if p.get("mobile_friendly") is True)
        mobile_evaluated = sum(1 for p in pages if p.get("mobile_friendly") is not None)
        metrics["mobile_friendly_pages"] = mobile_friendly
        metrics["mobile_friendly_evaluated"] = mobile_evaluated

    pending = await db.action_items.count_documents({"job_id": job_id, "status": "pending"})
    metrics["pending_action_items"] = pending
    # (the pending-approval backlog is workflow state, not a property of the site, so it is not a health issue)

    dup = await db.duplicate_content.find_one({"job_id": job_id})
    if dup:
        metrics["duplicate_pages"] = dup.get("duplicate_pages", 0)
        metrics["canonical_missing"] = dup.get("canonical_missing", 0)
        metrics["canonical_conflicts"] = dup.get("canonical_conflicting", 0) + dup.get("canonical_cross_domain", 0)
        if dup.get("duplicate_pages", 0) > 0:
            issues.append({"severity": "medium", "message": f"{dup.get('duplicate_pages')} page(s) are near-duplicates of other pages."})
        if dup.get("canonical_conflicting", 0) > 0:
            issues.append({"severity": "medium", "message": f"{dup.get('canonical_conflicting')} page(s) have conflicting canonical tags."})

    sd = await db.structured_data.find_one({"job_id": job_id})
    if sd:
        metrics["structured_data_valid"] = sd.get("valid", 0)
        metrics["structured_data_missing"] = sd.get("no_structured_data", 0)
        if sd.get("no_structured_data", 0) > 0:
            issues.append({"severity": "low", "message": f"{sd.get('no_structured_data')} page(s) have no structured data (Product/Article/Organization/Breadcrumb)."})
        if sd.get("invalid_types", 0) > 0:
            issues.append({"severity": "low", "message": f"{sd.get('invalid_types')} page(s) have invalid structured data markup."})

    geo = await db.geo_alignment.find_one({"job_id": job_id})
    if geo:
        metrics["geo_off_topic_pages"] = geo.get("off_topic_pages", 0)
        if geo.get("off_topic_pages", 0) > 0:
            issues.append({"severity": "low", "message": f"{geo.get('off_topic_pages')} page(s) diverge from the site's core industry — a risk for generative-search visibility."})

    orphans = await db.orphan_pages.find_one({"job_id": job_id})
    if orphans:
        metrics["orphan_pages"] = orphans.get("orphan_pages", 0)
        if orphans.get("orphan_pages", 0) > 0:
            issues.append({"severity": "medium", "message": f"{orphans.get('orphan_pages')} page(s) have no internal links pointing to them (orphans)."})

    sitemap_audit = await db.sitemap_audits.find_one({"job_id": job_id})
    if sitemap_audit:
        metrics["sitemap_found"] = sitemap_audit.get("sitemap_found", False)
        metrics["sitemap_valid"] = sitemap_audit.get("sitemap_valid", False)
        metrics["sitemap_uncrawled"] = sitemap_audit.get("uncrawled_urls_count", 0)
        if not sitemap_audit.get("sitemap_found", False):
            issues.append({"severity": "low", "message": "No XML sitemap found."})
        elif not sitemap_audit.get("sitemap_valid", False):
            issues.append({"severity": "medium", "message": "Sitemap found but could not be parsed."})
        if sitemap_audit.get("uncrawled_urls_count", 0) > 0:
            issues.append({"severity": "low", "message": f"{sitemap_audit.get('uncrawled_urls_count')} sitemap URL(s) were never crawled."})

    if n:
        deep = sum(1 for p in pages if (p.get("click_depth") or 0) > DEEP_CLICK_DEPTH)
        metrics["deep_click_depth_pages"] = deep
        if deep > 0:
            issues.append({"severity": "low", "message": f"{deep} page(s) are more than {DEEP_CLICK_DEPTH} clicks from the homepage (deep click depth)."})
        redirected = sum(1 for p in pages if (p.get("redirect_count") or 0) >= LONG_REDIRECT_CHAIN)
        metrics["long_redirect_chain_pages"] = redirected
        if redirected > 0:
            issues.append({"severity": "medium", "message": f"{redirected} page(s) are reached through 3+ hop redirect chains."})
        if https_pages != n:
            issues.append({"severity": "medium", "message": f"{n - https_pages} page(s) are linked over non-HTTPS entries (mixed content / host drift)."})
        if mobile_evaluated > 0 and mobile_friendly < mobile_evaluated:
            issues.append({"severity": "low", "message": f"{mobile_evaluated - mobile_friendly} of {mobile_evaluated} evaluated page(s) are missing a mobile viewport / zoom fix."})
        lh_redirected = (lh or {}).get("redirected_links")
        if lh_redirected:
            metrics["redirected_links"] = lh_redirected
            metrics["max_redirect_chain"] = (lh or {}).get("max_redirect_chain", 0)
            if (lh or {}).get("max_redirect_chain", 0) >= 3:
                issues.append({"severity": "low", "message": f"{lh_redirected} links redirect; longest chain is {lh.get('max_redirect_chain')} hops."})

    ai = await db.ai_visibility_summaries.find_one({"job_id": job_id})
    if ai:
        metrics["ai_visibility_score"] = ai.get("score")
        metrics["ai_blocked_agents"] = ai.get("blocked_ai_agents", [])
        metrics["ai_pricing_md"] = ai.get("pricing_md_present", False)
        metrics["ai_author_pages"] = ai.get("author_pages", 0)
        metrics["ai_fresh_pages"] = ai.get("fresh_pages", 0)
        if ai.get("blocked_ai_agents"):
            issues.append({"severity": "medium", "message": f"robots.txt blocks AI answer-engine crawlers: {', '.join(ai['blocked_ai_agents'][:4])} — those products cannot fetch the site's pages."})
        if not ai.get("llms_txt_present"):
            issues.append({"severity": "low", "message": "No llms.txt present for LLM consumers."})
        if not ai.get("pricing_md_present") and not ai.get("pricing_txt_present"):
            issues.append({"severity": "low", "message": "No /pricing.md machine-readable file for AI agents."})
        if (ai.get("author_pages") or 0) < 1 and (ai.get("scanned_pages") or 0) > 0:
            issues.append({"severity": "low", "message": "No author attribution detected on scanned pages (AI citation relies on E-E-A-T signals)."})

    local = await db.local_seo_summaries.find_one({"job_id": job_id})
    if local:
        metrics["local_seo_score"] = local.get("score")
        if local.get("score", 0) < 60:
            failed = [c.get("label", "") for c in (local.get("checks") or []) if not c.get("passed")][:3]
            missing = ", ".join(failed) if failed else f"score {local.get('score')}/100"
            issues.append({"severity": "low", "message": f"Local-SEO signals weak ({local.get('score')}/100): {missing}"})

    pseo = await db.programmatic_seo_audits.find_one({"job_id": job_id})
    if pseo:
        metrics["programmatic_seo_score"] = pseo.get("score")
        metrics["template_clusters"] = pseo.get("clusters_count", 0)
        metrics["template_pages"] = pseo.get("template_pages", 0)
        metrics["thin_template_pages"] = pseo.get("thin_template_pages", 0)
        metrics["duplicate_template_pages"] = pseo.get("duplicate_template_pages", 0)
        metrics["unlinked_template_pages"] = pseo.get("unlinked_template_pages", 0)
        if pseo.get("thin_template_pages", 0) > 0:
            issues.append({"severity": "medium", "message": f"{pseo.get('thin_template_pages')} programmatic thin page(s) under {pseo.get('total_pages', 0) or '?'} template pages — swapped-variable content risk."})
        if pseo.get("duplicate_template_pages", 0) > 0:
            issues.append({"severity": "medium", "message": f"{pseo.get('duplicate_template_pages')} programmatic pages are near-duplicates of other template pages."})
        if pseo.get("unlinked_template_pages", 0) > 0:
            issues.append({"severity": "medium", "message": f"{pseo.get('unlinked_template_pages')} programmatic pages have no internal links pointing to them (orphan spokes)."})

    hreflang = await db.hreflang_audits.find_one({"job_id": job_id})
    if hreflang:
        metrics["hreflang_score"] = hreflang.get("score")
        metrics["hreflang_locales"] = hreflang.get("locales") or []
        if hreflang.get("applicable"):
            failed = [c.get("label", "") for c in (hreflang.get("checks") or []) if not c.get("passed")]
            if hreflang.get("pages_with_hreflang", 0) == 0:
                issues.append({"severity": "high", "message": f"Multi-locale site ({len(hreflang.get('locales') or [])} locales) with no hreflang tags — wrong-language pages may index."})
            elif failed:
                issues.append({"severity": "medium", "message": f"hreflang errors ({hreflang.get('score')}/100): {', '.join(failed[:3])}"})

    uh = await db.url_hygiene_audits.find_one({"job_id": job_id})
    if uh:
        metrics["url_hygiene_score"] = uh.get("score")
        metrics["param_pages"] = uh.get("param_pages", 0)
        if uh.get("facet_pages", 0) > 0:
            issues.append({"severity": "medium", "message": f"{uh.get('facet_pages')} page(s) use faceted/pagination URL parameters — crawl budget + duplicate risk."})

    idx = await db.indexation_audits.find_one({"job_id": job_id})
    if idx:
        metrics["indexation_status"] = idx.get("status")
        metrics["indexed_estimate"] = idx.get("indexed_estimate")

    img = await db.image_optimization_audits.find_one({"job_id": job_id})
    if img:
        metrics["image_opt_score"] = img.get("score")
        metrics["images_total"] = img.get("total_images") or metrics.get("images_total")
        metrics["image_occurrences"] = img.get("image_occurrences") or metrics.get("images_total")
        if img.get("score") is not None and img["score"] < 60:
            issues.append({"severity": "low", "message": f"Image optimization weak ({img.get('score')}/100): modern formats and dimensions affect CWV/LCP."})

    result = compute_score(metrics)
    metrics["category_scores"] = result["category_scores"]

    health = {
        "job_id": job_id,
        "grade": result["grade"],
        "score": result["score"],
        "score_breakdown": result["score_breakdown"],
        "unmeasured_categories": result["unmeasured_categories"],
        "score_coverage_pct": result["score_coverage_pct"],
        "score_basis": "weighted mean of measured category scores; each category is the mean of its measured 0-100 components (see score_breakdown). Unmeasured categories are excluded, not scored as 100.",
        "metrics": metrics,
        "issues": issues,
        "generated_at": datetime.utcnow(),
    }
    await db.site_health.update_one(
        {"job_id": job_id},
        {"$set": health},
        upsert=True,
    )
    return health


async def get_site_health(job_id: str) -> dict | None:
    db = get_db()
    doc = await db.site_health.find_one({"job_id": job_id})
    if not doc:
        return await compute_site_health(job_id)
    doc["id"] = str(doc.pop("_id"))
    return doc
