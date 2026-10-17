"""Run the REAL crawler + analyzer + health roll-up once against the golden site."""

import asyncio
import logging

import pytest

from backend.tests.golden import site as gt

JOB = "golden"


async def _run():
    from mongomock_motor import AsyncMongoMockClient

    import backend.db.mongo as mongo
    from backend.services.crawler import crawl_site
    from backend.services.seo_analyzer import analyze_pages
    from backend.services.site_health import compute_site_health

    original_client = getattr(mongo, "client", None)
    mongo.client = AsyncMongoMockClient()
    db = mongo.client.rankengine
    srv = gt.serve()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        await db.analysis_jobs.insert_one({"_id": JOB, "id": JOB, "status": "running", "url": base + "/"})
        await asyncio.wait_for(crawl_site(JOB, base + "/", max_pages=60, use_playwright=False, mobile=False), timeout=120)
        await analyze_pages(JOB)
        health = await compute_site_health(JOB)
        pages = {p["url"].replace(base, "") or "/": p for p in await db.pages.find({"job_id": JOB}).to_list(1000)}
        issues: dict[str, set] = {}
        for a in await db.action_items.find({"job_id": JOB}).to_list(5000):
            path = (a.get("page_url") or a.get("url") or "").replace(base, "") or "/"
            issues.setdefault(path, set()).add(a.get("issue_key"))
        links = {l["url"].replace(base, "") or "/": l for l in await db.page_links.find({"job_id": JOB}).to_list(1000)}
        return {"base": base, "pages": pages, "links": links, "issues": issues, "health": health}
    finally:
        srv.shutdown()
        mongo.client = original_client  # never leak the mock into other tests


@pytest.fixture(scope="session")
def golden():
    logging.disable(logging.CRITICAL)
    try:
        return asyncio.run(_run())
    finally:
        logging.disable(logging.NOTSET)
