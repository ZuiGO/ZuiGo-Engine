"""local_seo / url_hygiene / local_insights: measured rates, no invented point buckets."""

import re

import pytest

from backend.services import local_insights as li
from backend.services import local_seo as ls
from backend.services import url_hygiene as uh


class Cur:
    def __init__(self, docs):
        self.docs = docs

    def __aiter__(self):
        async def gen():
            for d in self.docs:
                yield dict(d)
        return gen()

    async def to_list(self, length=None):
        return [dict(d) for d in self.docs]


class Col:
    def __init__(self, docs=None):
        self.docs = docs or []

    def find(self, *a, **k):
        return Cur(self.docs)

    async def find_one(self, *a, **k):
        return None

    async def update_one(self, *a, **k):
        return None


class Db:
    def __init__(self, pages):
        self._pages = pages

    def __getattr__(self, name):
        return Col(self._pages if name == "pages" else [])


# ---------------- local_seo ----------------

def test_a_bare_number_is_not_a_postal_code():
    assert not ls.POSTAL_RE.search("copyright 2024 - from 1999 only 49.99")
    assert ls.POSTAL_RE.search("nashik pin code 422010")
    assert ls.POSTAL_RE.search("zip: 78701")


async def _local(monkeypatch, html_pages):
    pages = [{"url": u, "html": h, "page_type": "home" if u.endswith("/") else "other"} for u, h in html_pages]
    monkeypatch.setattr(ls, "get_db", lambda: Db(pages))
    return await ls.check_local_seo("j")


@pytest.mark.asyncio
async def test_non_local_site_is_not_applicable_and_year_is_not_an_address(monkeypatch):
    s = await _local(monkeypatch, [("https://x.example/", "<html><body><p>Copyright 2024. Version 12345 released.</p></body></html>")])
    assert s["address_signals_present"] is False
    assert s["applicable"] is False
    assert s["score"] == round(100 * s["signals_present"] / s["signals_total"])


@pytest.mark.asyncio
async def test_local_business_signals_are_counted_without_weights(monkeypatch):
    ld = ('<script type="application/ld+json">{"@type":"LocalBusiness","name":"Cafe","telephone":"+911234567890",'
          '"address":{"@type":"PostalAddress","streetAddress":"5 MG Road","postalCode":"422010"}}</script>')
    s = await _local(monkeypatch, [("https://x.example/", f"<html><head>{ld}</head><body>Contact</body></html>")])
    assert s["applicable"] is True
    assert s["subscores"]["local_business_schema"] == 100 and s["subscores"]["reviews"] == 0
    assert s["score"] == round(100 * s["signals_present"] / 6)


# ---------------- url_hygiene ----------------

@pytest.mark.asyncio
async def test_url_hygiene_scores_are_page_shares(monkeypatch):
    urls = ["https://x.com/a", "https://x.com/b", "https://x.com/C_d", "https://x.com/e?x=1"]
    monkeypatch.setattr(uh, "get_db", lambda: Db([{"url": u} for u in urls]))
    out = await uh.audit_url_hygiene("j")
    assert out["subscores"]["parameter_control"] == 75   # 1 of 4 pages has parameters
    assert out["subscores"]["readable_paths"] == 75      # 1 of 4 has uppercase/underscore (counted once)
    assert out["subscores"]["slug_length"] == 100
    assert out["subscores"]["slash_consistency"] == 100  # all without trailing slash
    assert out["score"] == round((75 + 75 + 100 + 100) / 4)


# ---------------- local_insights ----------------

@pytest.mark.asyncio
async def test_local_onpage_score_is_mean_of_coverage_rates(monkeypatch):
    pages = [
        {"url": "a", "title": "T", "meta_description": "m", "h1_count": 1, "image_count": 2, "images_missing_alt": 1, "is_indexable": True},
        {"url": "b", "title": "", "meta_description": "", "h1_count": 0, "image_count": 0, "images_missing_alt": 0, "is_indexable": True},
        {"url": "gone", "status_code": 404, "title": "", "is_indexable": True},
    ]
    monkeypatch.setattr(li, "get_db", lambda: Db(pages))
    out = await li.local_onpage("j")
    assert out["pages_analyzed"] == 2  # the 404 is not a content page
    # alt 50, meta 50, h1 50, title 50, indexable 100 -> 60
    assert out["score"] == 60


@pytest.mark.asyncio
async def test_local_onpage_error_only_crawl_has_no_score(monkeypatch):
    monkeypatch.setattr(li, "get_db", lambda: Db([{"url": "x", "status_code": 500}]))
    assert await li.local_onpage("j") is None
