"""Remaining audit scores are measured rates, and 'nothing to measure' is never a perfect score."""

from datetime import datetime, timedelta

import pytest

from backend.services import catalogue_optimization as cat
from backend.services import content_freshness as fresh


class Cur:
    def __init__(self, docs):
        self.docs = list(docs)

    def __aiter__(self):
        async def gen():
            for d in self.docs:
                yield d
        return gen()


class Col:
    def __init__(self, docs):
        self.docs = docs
        self.saved = None

    def find(self, *a, **k):
        return Cur(self.docs)

    async def update_one(self, *a, **k):
        self.saved = True


class Db:
    def __init__(self, pages):
        self.pages = Col(pages)
        self.content_freshness_audits = Col([])
        self.catalogue_audits = Col([])

    def __getattr__(self, n):
        c = Col([])
        setattr(self, n, c)
        return c


@pytest.mark.asyncio
async def test_freshness_score_is_the_share_of_fresh_pages(monkeypatch):
    now = datetime.utcnow()
    pages = [{"url": f"u{i}", "last_modified": now - timedelta(days=d)} for i, d in enumerate([10, 20, 400, 500])]
    monkeypatch.setattr(fresh, "get_db", lambda: Db(pages))
    out = await fresh.audit_content_freshness("j")
    assert out["score"] == 50 and out["decayed_pages_count"] == 2


@pytest.mark.asyncio
async def test_freshness_without_any_dates_has_no_score(monkeypatch):
    monkeypatch.setattr(fresh, "get_db", lambda: Db([]))
    out = await fresh.audit_content_freshness("j")
    assert out["score"] is None


@pytest.mark.asyncio
async def test_catalogue_score_is_the_share_of_clean_category_urls(monkeypatch):
    pages = [{"url": "https://s/c1", "page_type": "category"}, {"url": "https://s/c2", "page_type": "category"},
             {"url": "https://s/c1?color=red", "page_type": "category"}, {"url": "https://s/p", "page_type": "product"}]
    monkeypatch.setattr(cat, "get_db", lambda: Db(pages))
    out = await cat.audit_catalogue("j")
    assert out["score"] == round(100 * 2 / 3)
    assert out["potential_crawl_trap"] is False


@pytest.mark.asyncio
async def test_catalogue_crawl_trap_is_a_stated_ratio_rule(monkeypatch):
    pages = [{"url": "https://s/c", "page_type": "category"}] + [
        {"url": f"https://s/c?f={i}", "page_type": "category"} for i in range(3)
    ]
    monkeypatch.setattr(cat, "get_db", lambda: Db(pages))
    out = await cat.audit_catalogue("j")
    assert out["potential_crawl_trap"] is True and out["score"] == 25
