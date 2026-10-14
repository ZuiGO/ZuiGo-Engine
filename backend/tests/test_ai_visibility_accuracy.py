"""AI-visibility must be computed from measured components, never from fixed buckets."""

import pytest

from backend.services import ai_visibility as ai_mod

GOOD_PAGE = (
    '<html lang="en"><head><script type="application/ld+json">{"@type":"Organization","name":"X"}</script>'
    "</head><body><h1>Q</h1><ul><li>a</li><li>b</li><li>c</li></ul></body></html>"
)


class Col:
    def __init__(self, store):
        self._s = store

    def find(self, q, projection=None):
        return self

    async def to_list(self, length=None):
        return [dict(x) for x in self._s.values()]

    async def find_one(self, q):
        for v in self._s.values():
            if all(v.get(k) == fv for k, fv in q.items()):
                return dict(v)

    async def update_one(self, q, update, upsert=False):
        key = next(iter(q.values()))
        self._s[key] = {**(self._s.get(key) or {}), **update.get("$set", {})}


class Db:
    def __init__(self):
        self.s = {"pages": {}, "sitemap_audits": {}, "ai_visibility_summaries": {}}

    def __getattr__(self, n):
        if n in self.s:
            return Col(self.s[n])
        raise AttributeError(n)


def run(monkeypatch, robots, pages, url="https://x.com", robots_status=200, sitemap=True):
    db = Db()
    monkeypatch.setattr(ai_mod, "get_db", lambda: db)
    fetched = []

    async def fake_fetch(u, ua, auth=None):
        fetched.append(u)
        if u.endswith("/robots.txt"):
            return (robots, robots_status) if robots is not None else (None, robots_status)
        return None, 404

    monkeypatch.setattr(ai_mod, "_fetch_plain", fake_fetch)
    for i, h in enumerate(pages):
        db.s["pages"][i] = {"job_id": "j", "url": f"{url}/p{i}", "html": h}
    db.s["sitemap_audits"]["s"] = {"job_id": "j", "sitemap_valid": sitemap}
    return db, fetched


@pytest.mark.asyncio
async def test_blocking_all_crawlers_lowers_the_score(monkeypatch):
    run(monkeypatch, "User-agent: *\nDisallow: /\n", [GOOD_PAGE])
    blocked = await ai_mod.check_ai_visibility("j", "https://x.com")
    run(monkeypatch, "User-agent: *\nAllow: /\n", [GOOD_PAGE])
    open_ = await ai_mod.check_ai_visibility("j", "https://x.com")
    assert blocked["subscores"]["crawl_access"] == 0
    assert open_["subscores"]["crawl_access"] == 100
    assert blocked["score"] < open_["score"]
    assert "oai-searchbot" in blocked["blocked_ai_agents"]


@pytest.mark.asyncio
async def test_training_only_block_is_reported_but_not_a_block(monkeypatch):
    run(monkeypatch, "User-agent: GPTBot\nUser-agent: CCBot\nDisallow: /\n", [GOOD_PAGE])
    s = await ai_mod.check_ai_visibility("j", "https://x.com")
    assert s["blocked_ai_agents"] == []
    assert set(s["blocked_training_agents"]) >= {"gptbot", "ccbot"}  # shared group handled
    assert s["subscores"]["crawl_access"] == 100


@pytest.mark.asyncio
async def test_unmeasurable_robots_is_excluded_not_scored(monkeypatch):
    run(monkeypatch, None, [GOOD_PAGE], robots_status=503)
    s = await ai_mod.check_ai_visibility("j", "https://x.com")
    assert s["subscores"]["crawl_access"] is None
    measured = [v for v in s["subscores"].values() if v is not None]
    assert s["score"] == round(sum(measured) / len(measured))


@pytest.mark.asyncio
async def test_score_is_mean_of_measured_components_without_cutoffs(monkeypatch):
    # 1 of 4 pages has structured data (25%): the old code scored this as 0 because of a 50% cut-off.
    pages = [GOOD_PAGE] + ["<html><body><p>plain</p></body></html>"] * 3
    run(monkeypatch, "", pages, sitemap=False)
    s = await ai_mod.check_ai_visibility("j", "https://x.com")
    assert s["subscores"]["structured_data"] == 25
    assert s["subscores"]["sitemap"] == 0
    measured = [v for v in s["subscores"].values() if v is not None]
    assert s["score"] == round(sum(measured) / len(measured))


@pytest.mark.asyncio
async def test_uses_the_targets_scheme_and_host(monkeypatch):
    _, fetched = run(monkeypatch, "", [GOOD_PAGE], url="http://127.0.0.1:8000")
    await ai_mod.check_ai_visibility("j", "http://127.0.0.1:8000/")
    assert "http://127.0.0.1:8000/robots.txt" in fetched
    assert not any(u.startswith("https://") for u in fetched)


@pytest.mark.asyncio
async def test_microdata_pages_count_as_structured(monkeypatch):
    md = '<html><body><div itemscope itemtype="https://schema.org/Product"><span itemprop="name">P</span></div></body></html>'
    run(monkeypatch, "", [md])
    s = await ai_mod.check_ai_visibility("j", "https://x.com")
    assert s["structured_data_pages"] == 1


@pytest.mark.asyncio
async def test_error_pages_are_ignored(monkeypatch):
    db, _ = run(monkeypatch, "", [GOOD_PAGE])
    db.s["pages"]["404"] = {"job_id": "j", "url": "https://x.com/gone", "html": "<html>nf</html>", "status_code": 404}
    s = await ai_mod.check_ai_visibility("j", "https://x.com")
    assert s["total_pages"] == 1
