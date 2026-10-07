"""Google Search Console integration: OAuth2 connect + Search Analytics data.

One-time setup (operator): create a Google Cloud OAuth client (Web app),
enable the Search Console API, and save the client id/secret in the app
Settings page (stored in MongoDB `app_settings`; GSC_CLIENT_ID /
GSC_CLIENT_SECRET in .env act as fallback). The analyzed domain must be a
verified property in Search Console.
"""

from datetime import datetime, timedelta
from urllib.parse import quote, urlencode

import httpx

from backend.config import settings
from backend.db.mongo import get_db
from backend.logging_setup import get_logger

logger = get_logger("gsc")

SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SITES_URL = "https://www.googleapis.com/webmasters/v3/sites"
SEARCH_ANALYTICS_URL = "https://www.googleapis.com/webmasters/v3/sites/{site}/searchAnalytics/query"
URL_INSPECTION_URL = "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"
SITEMAPS_URL = "https://www.googleapis.com/webmasters/v3/sites/{site}/sitemaps"


async def get_gsc_config() -> dict:
    """GSC OAuth config: MongoDB app_settings first, .env as fallback."""
    db = get_db()
    doc = await db.app_settings.find_one({"key": "gsc"}) or {}
    return {
        "client_id": doc.get("client_id") or settings.gsc_client_id,
        "client_secret": doc.get("client_secret") or settings.gsc_client_secret,
        "redirect_uri": doc.get("redirect_uri") or settings.gsc_redirect_uri,
    }


async def configured() -> bool:
    cfg = await get_gsc_config()
    return bool(cfg["client_id"] and cfg["client_secret"])


def _build_auth_url(job_id: str, client_id: str, redirect_uri: str) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": job_id,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def _redirect_uri_for(request) -> str:
    """Redirect URI for the current request: configured value, else derived
    from the request host (https://<host>/api/gsc/callback)."""
    base = f"{request.url.scheme}://{request.url.netloc}"
    return f"{base}/api/gsc/callback"


def _domain_from_url(url: str) -> str:
    if "//" in url:
        return url.split("//")[-1].split("/")[0]
    return url


def _match_property(sites: list[str], domain: str) -> str | None:
    d = (domain or "").lower()
    if not d:
        return None
    exact = f"sc-domain:{d}"
    if exact in sites:
        return exact
    normalized = {s.rstrip("/"): s for s in sites}
    for pref in ("https://www.", "https://", "http://www.", "http://"):
        if pref + d in normalized:
            return normalized[pref + d]
    return None


async def _get_credentials(domain: str) -> dict | None:
    db = get_db()
    return await db.gsc_credentials.find_one({"domain": domain})


async def _save_credentials(domain: str, creds: dict):
    db = get_db()
    await db.gsc_credentials.update_one(
        {"domain": domain},
        {"$set": {**creds, "domain": domain, "connected_at": creds.get("connected_at", datetime.utcnow())}},
        upsert=True,
    )


async def _token_post(payload: dict) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(TOKEN_URL, json=payload)
    if resp.status_code >= 400:
        raise RuntimeError(f"GSC OAuth failed (HTTP {resp.status_code}): {resp.text[:200]}")
    return resp.json()


async def exchange_code(code: str, job_id: str, redirect_uri: str | None = None) -> dict:
    db = get_db()
    job = await db.analysis_jobs.find_one({"_id": job_id})
    if not job:
        raise RuntimeError("Job not found")
    domain = _domain_from_url(job.get("url", ""))
    cfg = await get_gsc_config()
    data = await _token_post({
        "code": code,
        "client_id": cfg["client_id"],
        "client_secret": cfg["client_secret"],
        "redirect_uri": redirect_uri or cfg["redirect_uri"],
        "grant_type": "authorization_code",
    })
    if not data.get("refresh_token"):
        raise RuntimeError("OAuth response missing refresh_token (grant_type must be 'offline')")
    await _save_credentials(domain, {
        "access_token": data.get("access_token"),
        "refresh_token": data.get("refresh_token"),
        "expires_at": datetime.utcnow() + timedelta(seconds=data.get("expires_in", 3600)),
        "scope": data.get("scope", SCOPE),
    })
    return {"domain": domain, "ok": True}


async def _valid_access_token(domain: str) -> str | None:
    if settings.gsc_service_account_file:
        try:
            import google.auth
            from google.oauth2 import service_account
            from google.auth.transport.requests import Request
            import os
            
            # Check if file exists, if not relative to root
            filepath = settings.gsc_service_account_file
            if not os.path.exists(filepath):
                # Try relative to backend dir or project root
                filepath = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), settings.gsc_service_account_file)
                
            creds = service_account.Credentials.from_service_account_file(filepath, scopes=[SCOPE])
            creds.refresh(Request())
            return creds.token
        except Exception as e:
            logger.error("Failed to get token from service account %s: %s", settings.gsc_service_account_file, e)

    if settings.gsc_refresh_token:
        try:
            cfg = await get_gsc_config()
            if cfg["client_id"] and cfg["client_secret"]:
                data = await _token_post({
                    "client_id": cfg["client_id"],
                    "client_secret": cfg["client_secret"],
                    "refresh_token": settings.gsc_refresh_token,
                    "grant_type": "refresh_token",
                })
                return data.get("access_token")
        except Exception as e:
            logger.error("Failed to get token from .env refresh_token: %s", e)

    creds = await _get_credentials(domain)
    if not creds:
        return None
    expires = creds.get("expires_at")
    if expires and expires > datetime.utcnow() + timedelta(minutes=5):
        return creds.get("access_token")
    try:
        cfg = await get_gsc_config()
        data = await _token_post({
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
            "refresh_token": creds.get("refresh_token"),
            "grant_type": "refresh_token",
        })
        updated = {**creds,
                   "access_token": data.get("access_token"),
                   "expires_at": datetime.utcnow() + timedelta(seconds=data.get("expires_in", 3600))}
        await _save_credentials(domain, updated)
        return updated.get("access_token")
    except Exception as e:
        logger.warning("GSC token refresh failed domain=%s: %s", domain, e)
        return None


async def list_sites(domain: str) -> list[str]:
    token = await _valid_access_token(domain)
    if not token:
        raise RuntimeError("GSC not connected for this domain")
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(SITES_URL, headers={"Authorization": f"Bearer {token}"})
    if resp.status_code >= 400:
        raise RuntimeError(f"GSC sites list failed (HTTP {resp.status_code}): {resp.text[:200]}")
    return [s.get("siteUrl") for s in resp.json().get("siteEntry", [])]


async def _analytics_query(site: str, domain: str, dimensions: list[str], days: int = 28, search_type: str = "web", row_limit: int = 25) -> list[dict]:
    token = await _valid_access_token(domain)
    if not token:
        raise RuntimeError("GSC not connected for this domain")
    start = (datetime.utcnow() - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    end = datetime.utcnow().strftime("%Y-%m-%d")
    
    payload = {"startDate": start, "endDate": end, "dimensions": dimensions, "rowLimit": row_limit}
    if search_type != "web":
        payload["type"] = search_type

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            SEARCH_ANALYTICS_URL.format(site=quote(site, safe="")),
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )
    if resp.status_code >= 400:
        logger.warning(f"GSC search analytics failed (HTTP {resp.status_code}): {resp.text[:200]}")
        return []
    return resp.json().get("rows") or []


def _summarize(rows: list[dict]) -> dict:
    clicks = sum(r.get("clicks", 0) for r in rows)
    impressions = sum(r.get("impressions", 0) for r in rows)
    weighted_position = sum((r.get("position") or 0) * (r.get("impressions") or 0) for r in rows)
    return {
        "clicks": clicks,
        "impressions": impressions,
        "ctr": round(clicks / impressions, 4) if impressions else 0.0,
        "position": round(weighted_position / impressions, 1) if impressions else None,
    }


async def list_sitemaps(domain: str) -> list[dict]:
    token = await _valid_access_token(domain)
    if not token:
        raise RuntimeError("GSC not connected for this domain")
    
    creds = await _get_credentials(domain) or {}
    site = creds.get("property")
    if not site:
        sites = await list_sites(domain)
        site = _match_property(sites, domain)
        if not site:
            return []
            
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            SITEMAPS_URL.format(site=quote(site, safe="")),
            headers={"Authorization": f"Bearer {token}"}
        )
    if resp.status_code >= 400:
        logger.warning(f"GSC sitemaps list failed (HTTP {resp.status_code}): {resp.text[:200]}")
        return []
    return resp.json().get("sitemap", [])


async def fetch_gsc(domain: str, days: int = 28) -> dict | None:
    token = await _valid_access_token(domain)
    if not token:
        return None
        
    sites = await list_sites(domain)
    site = _match_property(sites, domain)
    if not site:
        raise RuntimeError(
            f"Domain {domain} is not a verified Search Console property. "
            "Verify it in Search Console first (found: " + (", ".join(sites[:5]) or "none") + ")."
        )
    q_rows = await _analytics_query(site, domain, ["query"], days, row_limit=100)
    p_rows = await _analytics_query(site, domain, ["page"], days, row_limit=100)
    c_risks = await _cannibalization_query(site, domain, days)
    
    # Granular dimensions
    device_rows = await _analytics_query(site, domain, ["device"], days, row_limit=10)
    country_rows = await _analytics_query(site, domain, ["country"], days, row_limit=20)
    appearance_rows = await _analytics_query(site, domain, ["searchAppearance"], days, row_limit=20)
    
    # Other search types
    discover_rows = await _analytics_query(site, domain, ["page"], days, search_type="discover", row_limit=25)
    news_rows = await _analytics_query(site, domain, ["page"], days, search_type="googleNews", row_limit=25)
    
    sitemaps = await list_sitemaps(domain)
    
    totals = _summarize(q_rows)
    creds = await _get_credentials(domain) or {}
    await _save_credentials(domain, {**creds, "property": site})
    
    def _format_rows(rows, key_name):
        return [
            {key_name: r["keys"][0], "clicks": r.get("clicks", 0),
             "impressions": r.get("impressions", 0),
             "ctr": round(r.get("clicks", 0) / r.get("impressions", 1), 4) if r.get("impressions") else 0,
             "position": r.get("position")}
            for r in rows if r.get("keys")
        ]

    return {
        "property": site,
        "days": days,
        "fetched_at": datetime.utcnow(),
        **totals,
        "queries": _format_rows(q_rows, "query"),
        "pages": _format_rows(p_rows, "page"),
        "devices": _format_rows(device_rows, "device"),
        "countries": _format_rows(country_rows, "country"),
        "search_appearance": _format_rows(appearance_rows, "appearance"),
        "discover_pages": _format_rows(discover_rows, "page"),
        "news_pages": _format_rows(news_rows, "page"),
        "sitemaps": sitemaps,
        "cannibalization_risks": c_risks,
    }


async def gsc_status(domain: str) -> dict:
    creds = await _get_credentials(domain) or {}
    env_configured = bool(settings.gsc_service_account_file or settings.gsc_refresh_token)
    cfg_ok = await configured() or env_configured
    
    if not creds and not env_configured:
        return {"connected": False, "configured": cfg_ok, "domain": domain, "property": None}
        
    return {
        "connected": True,
        "configured": cfg_ok,
        "domain": domain,
        "property": creds.get("property"),
        "token_expires_at": creds.get("expires_at"),
        "connected_at": creds.get("connected_at"),
    }


async def disconnect(domain: str) -> None:
    db = get_db()
    await db.gsc_credentials.delete_many({"domain": domain})


async def inspect_url(domain: str, url: str) -> dict:
    token = await _valid_access_token(domain)
    if not token:
        raise RuntimeError("GSC not connected for this domain")
        
    creds = await _get_credentials(domain) or {}
    site = creds.get("property")
    if not site:
        sites = await list_sites(domain)
        site = _match_property(sites, domain)
        if not site:
            raise RuntimeError(f"Domain {domain} is not a verified Search Console property.")
            
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            URL_INSPECTION_URL,
            headers={"Authorization": f"Bearer {token}"},
            json={
                "inspectionUrl": url,
                "siteUrl": site,
                "languageCode": "en-US"
            }
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"GSC URL inspection failed (HTTP {resp.status_code}): {resp.text[:200]}")
    return resp.json().get("inspectionResult") or {}


async def _cannibalization_query(site: str, domain: str, days: int = 28) -> list[dict]:
    token = await _valid_access_token(domain)
    if not token:
        raise RuntimeError("GSC not connected for this domain")
    start = (datetime.utcnow() - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    end = datetime.utcnow().strftime("%Y-%m-%d")
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            SEARCH_ANALYTICS_URL.format(site=quote(site, safe="")),
            headers={"Authorization": f"Bearer {token}"},
            json={"startDate": start, "endDate": end, "dimensions": ["query", "page"], "rowLimit": 1000},
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"GSC search analytics failed (HTTP {resp.status_code}): {resp.text[:200]}")
    
    rows = resp.json().get("rows") or []
    
    from collections import defaultdict
    groups = defaultdict(list)
    for r in rows:
        if len(r.get("keys", [])) < 2:
            continue
        q = r["keys"][0]
        p = r["keys"][1]
        groups[q].append({
            "page": p,
            "clicks": r.get("clicks", 0),
            "impressions": r.get("impressions", 0),
            "position": r.get("position", 0),
            "ctr": round(r.get("clicks", 0) / r.get("impressions", 1), 4) if r.get("impressions") else 0
        })
        
    cannibalization = []
    for q, pages in groups.items():
        sig_pages = [p for p in pages if p["impressions"] >= 10]
        if len(sig_pages) > 1:
            sig_pages.sort(key=lambda x: x["impressions"], reverse=True)
            if sig_pages[1]["impressions"] >= 50:
                cannibalization.append({
                    "query": q,
                    "pages": sig_pages,
                    "total_impressions": sum(p["impressions"] for p in sig_pages),
                })
                
    cannibalization.sort(key=lambda x: x["total_impressions"], reverse=True)
    return cannibalization
