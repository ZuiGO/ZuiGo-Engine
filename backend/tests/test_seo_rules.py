import pytest

from backend.services.seo_rules import basis_for, is_thin, staging_label, thin_threshold


@pytest.mark.parametrize("host,label", [
    ("dev.example.com", "dev"), ("staging.example.co.uk", "staging"), ("staging-site.example.com", "staging"),
    ("app.uat.example.com", "uat"), ("preview.acme.io", "preview"), ("qa-1.example.com", "qa"),
])
def test_real_non_prod_hosts_are_detected(host, label):
    assert staging_label(host) == label


@pytest.mark.parametrize("host", [
    "developer.mozilla.org", "latest-news.com", "www.contestwinners.in", "devon-holidays.co.uk",
    "attestation.example.com", "shop.example.com", "test.com", "example.co.uk", "127.0.0.1", "localhost",
    "dev.co.uk", "www.example.com", "protest.example.org", "devops.example.com",
])
def test_normal_hosts_are_not_flagged(host):
    assert staging_label(host) is None


def test_thin_threshold_by_page_type():
    assert thin_threshold("Product detail") == 150
    assert thin_threshold("category") == 700
    assert thin_threshold("legal") == 50
    assert thin_threshold("blog") == 350
    assert thin_threshold(None) == 350


def test_is_thin_uses_main_content_words():
    assert is_thin({"word_count": 349, "page_type": "blog"}) == (True, 350)
    assert is_thin({"word_count": 350, "page_type": "blog"}) == (False, 350)


def test_basis_classification():
    assert basis_for("title_missing") == "measured"
    assert basis_for("thin_content") == "rule"
    assert basis_for("staging_leakage") == "heuristic"
    assert basis_for("something_new") == "heuristic"  # unknown findings are never presented as facts
