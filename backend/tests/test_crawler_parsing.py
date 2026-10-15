"""Pure-function checks for the new indexability/URL/word-count behaviour."""

import pytest
from bs4 import BeautifulSoup

from backend.services.crawler import _main_content_word_count
from backend.services.indexability import parse_indexability
from backend.services.url_normalizer import normalize_url


class H(dict):  # case-insensitive-ish header stand-in
    def get(self, k, d=None):
        return super().get(k.lower(), d)


def idx(metas=(), headers=None):
    return parse_indexability(list(metas), headers)


def test_meta_robots_noindex():
    assert idx([("robots", "noindex, follow")])["noindex"] is True


def test_meta_name_is_case_insensitive_and_googlebot_applies():
    assert idx([("Robots", "NOINDEX")])["noindex"] is True
    r = idx([("googlebot", "noindex")])
    assert r["noindex"] is True and r["sources"] == ["meta:googlebot"]


def test_x_robots_tag_header_applies():
    r = idx(headers=H({"x-robots-tag": "noindex"}))
    assert r["noindex"] is True and r["sources"] == ["header:x-robots-tag"]


def test_header_bot_scoping():
    assert idx(headers=H({"x-robots-tag": "googlebot: noindex"}))["noindex"] is True
    assert idx(headers=H({"x-robots-tag": "otherbot: noindex"}))["noindex"] is False
    assert idx(headers=H({"x-robots-tag": "unavailable_after: 25 Jun 2030 15:00:00 PST"}))["noindex"] is False


def test_none_directive_means_noindex_nofollow():
    r = idx([("robots", "none")])
    assert r["noindex"] and r["nofollow"]


def test_irrelevant_meta_does_not_trigger():
    assert idx([("description", "noindex is a word here"), ("robots", "index,follow")])["noindex"] is False


@pytest.mark.parametrize("href", ["mailto:a@b.co", "tel:+123", "javascript:void(0)", "sms:123", "data:text/plain,x", "ftp://x.co/f", "whatsapp://send"])
def test_non_web_schemes_are_not_urls(href):
    assert normalize_url(href) == ""


def test_normal_urls_still_work():
    assert normalize_url("https://Example.com/a/") == "https://example.com/a"
    assert normalize_url("example.com/x") == "https://example.com/x"
    assert normalize_url("http://localhost:3000/p") == "http://localhost:3000/p"
    assert normalize_url("example.com:8080/p") == "https://example.com:8080/p"


def test_word_count_ignores_chrome_scripts_and_does_not_mutate_soup():
    html = (
        "<html><body><header><nav><a href='/a'>Home About Pricing Contact</a></nav></header>"
        "<main><h1>Title</h1><p>one two three four five</p><script>var junk = 1 2 3 4 5 6 7 8</script></main>"
        "<footer>copyright all rights reserved company</footer></body></html>"
    )
    soup = BeautifulSoup(html, "lxml")
    assert _main_content_word_count(soup) == 6  # Title + 5 words
    assert soup.find("nav") is not None and soup.find("footer") is not None  # soup untouched


def test_word_count_without_main_falls_back_to_body_minus_chrome():
    soup = BeautifulSoup("<html><body><nav>a b c</nav><p>x y z w</p><footer>f g</footer></body></html>", "lxml")
    assert _main_content_word_count(soup) == 4
