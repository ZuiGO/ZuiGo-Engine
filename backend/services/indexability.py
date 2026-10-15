"""Indexing directives from <meta name=robots|googlebot|bingbot> and X-Robots-Tag.

Google combines every applicable directive and the most restrictive one wins,
so a page is non-indexable if *any* applicable source says ``noindex`` (or
``none``). Directives scoped to other crawlers (e.g. ``otherbot: noindex``) do
not apply to Google/Bing and are ignored.
"""

from __future__ import annotations

APPLICABLE_BOTS = {"googlebot", "bingbot"}
META_NAMES = {"robots", "googlebot", "bingbot"}
_DIRECTIVES = {
    "all", "none", "noindex", "nofollow", "noarchive", "nosnippet", "notranslate",
    "noimageindex", "unavailable_after", "max-snippet", "max-image-preview",
    "max-video-preview", "indexifembedded", "nositelinkssearchbox",
}


def _tokens(value: str) -> set[str]:
    return {t.strip().lower() for t in (value or "").split(",") if t.strip()}


def _header_values(headers) -> list[str]:
    if headers is None:
        return []
    try:  # httpx.Headers keeps repeated headers
        vals = headers.get_list("x-robots-tag")
        if vals:
            return list(vals)
    except Exception:
        pass
    v = headers.get("x-robots-tag") if hasattr(headers, "get") else None
    return [v] if v else []


def _applicable_header_tokens(value: str) -> set[str]:
    """Directive tokens of one X-Robots-Tag value that apply to Google/Bing."""
    value = (value or "").strip()
    if ":" in value:
        head, rest = value.split(":", 1)
        if head.strip().lower() not in _DIRECTIVES:  # "<bot>: directives" form
            return _tokens(rest) if head.strip().lower() in APPLICABLE_BOTS else set()
    return _tokens(value)


def parse_indexability(meta_robots: list[tuple[str, str]], headers=None) -> dict:
    """meta_robots: [(meta name, content)] for every <meta name=...> on the page."""
    sources: list[str] = []
    noindex = nofollow = False
    for name, content in meta_robots:
        if (name or "").strip().lower() not in META_NAMES:
            continue
        toks = _tokens(content)
        if toks & {"noindex", "none"}:
            noindex = True
            sources.append(f"meta:{name.strip().lower()}")
        if toks & {"nofollow", "none"}:
            nofollow = True
    for value in _header_values(headers):
        toks = _applicable_header_tokens(value)
        if toks & {"noindex", "none"}:
            noindex = True
            sources.append("header:x-robots-tag")
        if toks & {"nofollow", "none"}:
            nofollow = True
    return {"noindex": noindex, "nofollow": nofollow, "sources": sorted(set(sources))}
