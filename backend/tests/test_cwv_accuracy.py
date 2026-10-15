"""Core Web Vitals: Google's thresholds, real PSI field keys, no metric substitution.

The payload mirrors PageSpeed Insights v5's documented shape (field metric names such as
LARGEST_CONTENTFUL_PAINT_MS, per-metric `category`, CLS percentile scaled x100).
"""

import pytest

from backend.services import performance_service as perf

PSI = {
    "loadingExperience": {"metrics": {
        "LARGEST_CONTENTFUL_PAINT_MS": {"percentile": 2100, "category": "FAST"},
        "INTERACTION_TO_NEXT_PAINT": {"percentile": 250, "category": "AVERAGE"},
        "CUMULATIVE_LAYOUT_SHIFT_SCORE": {"percentile": 5, "category": "FAST"},
        "FIRST_CONTENTFUL_PAINT_MS": {"percentile": 1500, "category": "FAST"},
    }},
    "lighthouseResult": {"audits": {
        "largest-contentful-paint": {"numericValue": 3000},
        "cumulative-layout-shift": {"numericValue": 0.2},
        "max-potential-fid": {"numericValue": 90},
        "total-blocking-time": {"numericValue": 120},
    }},
}


def test_real_psi_field_keys_are_parsed():
    exp = perf._field_experience(PSI)
    assert exp["values"]["lcp"] == 2100
    assert exp["values"]["inp"] == 250
    assert exp["values"]["cls"] == pytest.approx(0.05)  # percentile 5 == 0.05
    assert {k: exp["categories"][k] for k in ("lcp", "inp", "cls")} == {"lcp": "good", "inp": "needs-improvement", "cls": "good"}
    assert exp["scope"] == "url"


@pytest.mark.parametrize("metric,value,expected", [
    ("lcp", 2500, "good"), ("lcp", 2501, "needs-improvement"), ("lcp", 4000, "needs-improvement"), ("lcp", 4001, "poor"),
    ("inp", 200, "good"), ("inp", 500, "needs-improvement"), ("inp", 501, "poor"),
    ("cls", 0.1, "good"), ("cls", 0.25, "needs-improvement"), ("cls", 0.26, "poor"),
])
def test_classification_uses_googles_thresholds(metric, value, expected):
    assert perf.classify_metric(metric, value) == expected


def test_assessment_fails_when_any_metric_is_not_good():
    exp = perf._field_experience(PSI)
    a = perf.cwv_assessment(exp["values"], exp["categories"])
    assert a["overall"] == "failed" and a["inp"] == "needs-improvement"


def test_assessment_passes_when_all_good_and_tolerates_missing_inp():
    assert perf.cwv_assessment({"lcp": 2000, "inp": 150, "cls": 0.05})["overall"] == "passed"
    assert perf.cwv_assessment({"lcp": 2000, "cls": 0.05})["overall"] == "passed"  # no INP data
    assert perf.cwv_assessment({"lcp": 2000})["overall"] == "insufficient-data"
    assert perf.cwv_assessment({})["overall"] == "insufficient-data"


def test_lab_only_never_produces_an_assessment_and_inp_is_not_faked():
    lab = perf._lab_metrics(PSI["lighthouseResult"])
    assert lab["inp"] is None  # max-potential-fid (90) must NOT be reported as INP
    assert lab["tbt"] == 120
    assert perf.cwv_assessment({})["overall"] == "insufficient-data"


def test_origin_data_fills_metrics_the_url_lacks():
    data = {
        "loadingExperience": {"metrics": {"LARGEST_CONTENTFUL_PAINT_MS": {"percentile": 1800, "category": "FAST"}}},
        "originLoadingExperience": {"metrics": {
            "LARGEST_CONTENTFUL_PAINT_MS": {"percentile": 9000, "category": "SLOW"},
            "INTERACTION_TO_NEXT_PAINT": {"percentile": 120, "category": "FAST"},
        }},
    }
    exp = perf._field_experience(data)
    assert exp["values"]["lcp"] == 1800  # URL-level wins
    assert exp["values"]["inp"] == 120
    assert exp["scope"] == "mixed"


def test_google_category_wins_over_a_disagreeing_derived_value():
    data = {"loadingExperience": {"metrics": {"CUMULATIVE_LAYOUT_SHIFT_SCORE": {"percentile": 30, "category": "AVERAGE"}}}}
    exp = perf._field_experience(data)
    assert perf.cwv_assessment(exp["values"], exp["categories"])["cls"] == "needs-improvement"


def test_cwv_score_is_reproducible_from_values():
    assert perf._cwv_score({"lcp": 2000, "inp": 600, "cls": 0.05}) == round(100 * 2 / 3)
    assert perf._cwv_score({}) is None


@pytest.mark.asyncio
async def test_sampling_always_includes_the_homepage(monkeypatch):
    pages = [{"url": f"https://x.com/{c}", "page_type": "blog", "click_depth": 1, "status_code": 200} for c in "abcdef"]
    pages.append({"url": "https://x.com/", "page_type": "home", "click_depth": 0, "status_code": 200})
    pages.append({"url": "https://x.com/gone", "page_type": "blog", "click_depth": 1, "status_code": 404})

    class Col:
        def __init__(self, docs): self.docs = docs
        def find(self, *a, **k): return self
        async def to_list(self, length=None): return [dict(d) for d in self.docs]
        async def update_one(self, *a, **k): return None

    page_docs = pages

    class Db:
        pages = Col(page_docs)
        page_performance = Col([])
        page_performance_summaries = Col([])

    fetched = []

    async def fake_fetch(url, strategy="mobile"):
        fetched.append((url, strategy))
        return {"url": url, "strategy": strategy, "cwv": {}, "cwv_score": None, "cwv_source": "lab", "field": {}}

    monkeypatch.setattr(perf, "get_db", lambda: Db())
    monkeypatch.setattr(perf, "fetch_page_performance", fake_fetch)
    summary = await perf.fetch_performance("j", max_pages=3)
    urls = {u for u, _ in fetched}
    assert "https://x.com/" in urls            # homepage sampled (it used to be dropped)
    assert "https://x.com/gone" not in urls    # error pages are not sampled
    assert summary["sample_size"] == 3 and summary["pages_total"] == 7
