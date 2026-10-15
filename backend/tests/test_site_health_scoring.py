"""The health score must be reproducible from measured components; missing data must never score 100."""

import pytest

from backend.services.site_health import SCORE_WEIGHTS, compute_score


def comp(res, cat, name):
    c = next(b for b in res["score_breakdown"] if b["category"] == cat)
    return next(x["value"] for x in c["components"] if x["name"] == name)


def test_no_data_means_no_score_not_a_perfect_score():
    r = compute_score({})
    assert r["score"] is None and r["grade"] == "N/A"
    assert set(r["unmeasured_categories"]) == set(SCORE_WEIGHTS)
    assert r["score_coverage_pct"] == 0


def test_unmeasured_categories_are_excluded_not_scored_100():
    # Only on-page data exists: 50% meta, 50% H1. The old engine would have padded the other
    # categories with 100 and reported ~92.
    r = compute_score({"meta_description_coverage": 50, "h1_coverage": 50})
    assert r["score"] == 50
    assert r["score_coverage_pct"] == SCORE_WEIGHTS["on_page"]
    assert "performance" in r["unmeasured_categories"]


def test_weighted_mean_over_measured_categories_only():
    r = compute_score({"meta_description_coverage": 100, "h1_coverage": 100, "cwv_pass_rate": 0})
    w_on, w_perf = SCORE_WEIGHTS["on_page"], SCORE_WEIGHTS["performance"]
    assert r["score"] == round((w_on * 100 + w_perf * 0) / (w_on + w_perf))


def test_rates_scale_with_site_size_not_raw_counts():
    small = compute_score({"pages_analyzed": 10, "deep_click_depth_pages": 5})
    large = compute_score({"pages_analyzed": 1000, "deep_click_depth_pages": 500})
    assert comp(small, "technical", "crawl_depth") == comp(large, "technical", "crawl_depth") == 50.0
    # old formula subtracted raw counts: 500 deep pages wiped out the whole category regardless of site size


def test_error_pages_reduce_technical_score_via_rate():
    r = compute_score({"pages_crawled": 20, "pages_analyzed": 18, "error_pages": 2})
    assert comp(r, "technical", "http_errors") == 90.0


def test_content_not_thin_uses_evaluated_pool():
    r = compute_score({"thin_pages": 1, "pages_evaluated_word_count": 4})
    assert comp(r, "content", "not_thin") == 75.0
    assert comp(compute_score({"thin_pages": 0}), "content", "not_thin") is None  # nothing evaluated


def test_audits_that_did_not_run_do_not_count_as_clean():
    r = compute_score({"pages_analyzed": 10})
    assert comp(r, "links", "not_orphaned") is None
    assert comp(r, "schema_a11y", "structured_data_coverage") is None
    assert comp(r, "content", "not_duplicate") is None
    r2 = compute_score({"pages_analyzed": 10, "orphan_pages": 0})
    assert comp(r2, "links", "not_orphaned") == 100.0


def test_breakdown_reproduces_the_score():
    m = {"pages_analyzed": 10, "pages_crawled": 10, "meta_description_coverage": 80, "h1_coverage": 90,
         "title_coverage": 100, "cwv_pass_rate": 40, "broken_link_rate": 5.0,
         "https_entry_pages": 10, "https_evaluated": 10}
    r = compute_score(m)
    num = den = 0
    for b in r["score_breakdown"]:
        vals = [c["value"] for c in b["components"] if c["value"] is not None]
        if vals:
            num += b["weight"] * (sum(vals) / len(vals))
            den += b["weight"]
    assert r["score"] == round(num / den)


def test_security_only_counts_pages_that_were_evaluated():
    assert comp(compute_score({"https_entry_pages": 0}), "security", "https_pages") is None
    assert comp(compute_score({"https_entry_pages": 3, "https_evaluated": 4}), "security", "https_pages") == 75.0
