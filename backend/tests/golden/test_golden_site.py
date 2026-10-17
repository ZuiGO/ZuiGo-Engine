"""End-to-end accuracy: the app's findings must match facts we know about the fixture site."""

import pytest

from backend.tests.golden import site as gt


def test_every_real_page_is_crawled_in_every_language(golden):
    missing = [u for u in gt.TRUE_URLS if u not in golden["pages"]]
    assert not missing, f"pages silently dropped: {missing}"
    assert golden["pages"]["/hindi"]["lang"] == "hi" and golden["pages"]["/de"]["lang"] == "de"


@pytest.mark.parametrize("path,indexable", [
    ("/noindex-meta", False), ("/noindex-gbot", False), ("/noindex-hdr", False),
    ("/", True), ("/hindi", True), ("/canon", True), ("/desc-case", True),
])
def test_indexability(golden, path, indexable):
    assert golden["pages"][path]["is_indexable"] is indexable


def test_noindex_sources_are_recorded(golden):
    assert golden["pages"]["/noindex-hdr"]["noindex_sources"] == ["header:x-robots-tag"]
    assert golden["pages"]["/noindex-gbot"]["noindex_sources"] == ["meta:googlebot"]


def test_extracted_page_facts(golden):
    p = golden["pages"]
    assert p["/desc-case"]["meta_description"], "<meta name='Description'> (capital D) is a meta description"
    assert p["/no-title"]["title"] == "" and not p["/no-title"]["meta_description"] and p["/no-title"]["h1_count"] == 0
    assert p["/multi-h1"]["h1_count"] == 2
    assert p["/thin"]["word_count"] < 60, "inline <script>/<style> text must not count as words"
    assert p["/"]["word_count"] >= 500
    assert p["/alt"]["image_count"] == 3 and p["/alt"]["images_missing_alt"] == 1  # alt="" is decorative, not missing


def test_structured_data_detection(golden):
    assert golden["pages"]["/"]["has_structured_data"] is True
    assert golden["pages"]["/thin"]["has_structured_data"] is False


def test_error_page_is_marked_and_not_treated_as_content(golden):
    gone = golden["pages"]["/missing-page"]
    assert gone["status_code"] == 404 and gone["is_error_page"] is True
    assert golden["issues"]["/missing-page"] == {"page_http_error"}


def test_non_web_links_are_not_extracted(golden):
    page = golden["links"]["/links"]
    internal, external = page.get("internal_link_urls", []), page.get("external_link_urls", [])
    for url in internal + external:
        assert url.startswith(("http://", "https://")), url
        assert not any(bad in url for bad in ("mailto", "tel:", "javascript")), url
    assert not any(u.rstrip("/").endswith("/links") for u in internal), "a #fragment link is not a link to crawl"
    assert any("external.example" in u for u in external)
    assert any(u.endswith("/missing-page") for u in internal)
    assert len(external) == 1  # mailto / tel / javascript are not external links


EXPECTED = {
    "/thin": {"thin_content"},
    "/no-title": {"title_missing", "meta_description_missing", "h1_missing"},
    "/multi-h1": {"h1_multiple"},
    "/noindex-meta": {"noindex_page"},
    "/noindex-gbot": {"noindex_page"},
    "/noindex-hdr": {"noindex_page"},
}


@pytest.mark.parametrize("path,expected", EXPECTED.items())
def test_known_problems_are_reported(golden, path, expected):
    assert expected <= golden["issues"].get(path, set())


def test_no_false_positives_on_clean_facts(golden):
    issues = golden["issues"]
    assert "meta_description_missing" not in issues.get("/desc-case", set())
    assert "thin_content" not in {k for path, ks in issues.items() if path != "/thin" for k in ks}, "only /thin is thin"
    assert not any("staging_leakage" in ks for ks in issues.values()), "127.0.0.1 is not a staging host"
    for path in ("/hindi", "/de"):
        assert not ({"title_missing", "h1_missing", "thin_content"} & issues.get(path, set()))
    assert "h1_missing" not in issues.get("/", set())


def test_findings_carry_a_basis_not_a_made_up_confidence(golden):
    health = golden["health"]
    assert health["score"] is not None
    # No CWV data was collected: performance must be reported as unmeasured, never as a free 100.
    assert "performance" in health["unmeasured_categories"]
    perf = next(b for b in health["score_breakdown"] if b["category"] == "performance")
    assert perf["measured"] is False and perf["score"] is None


def test_health_metrics_use_content_pages_only(golden):
    m = golden["health"]["metrics"]
    assert m["error_pages"] == 1
    assert m["pages_crawled"] == m["pages_analyzed"] + 1
    assert m["thin_pages"] == 1
    assert m["title_coverage"] < 100  # /no-title
