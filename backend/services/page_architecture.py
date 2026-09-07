"""Build an evidence-backed product-page hierarchy from a completed crawl.

The crawler stores each page's HTML, which lets us use the site's own
BreadcrumbList markup before falling back to URL segments.  That distinction is
preserved in the output: product trees must not imply an editorial taxonomy the
crawl did not actually observe.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from bs4 import BeautifulSoup


_PRODUCT_SEGMENTS = {"product", "products", "product-catalogue", "product-catalog"}
_PRODUCT_CRUMBS = {
    "product",
    "products",
    "product catalogue",
    "product catalog",
    "our products",
}


def _normalise_label(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _clean_label(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _canonical_url(value: str) -> str:
    parsed = urlsplit(value)
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _url_label(value: str) -> str:
    words = re.sub(r"[-_]+", " ", value).strip()
    return words.title() if words else "Unclassified"


def _title_label(page: dict[str, Any]) -> str:
    title = _clean_label(page.get("title"))
    if title:
        # Site names are commonly appended after a separator.  The first part
        # is a more useful page label when breadcrumb evidence is unavailable.
        return re.split(r"\s+[|–—]\s+", title, maxsplit=1)[0].strip() or title
    return _url_label(urlsplit(page.get("url", "")).path.rsplit("/", 1)[-1])


def _walk_json(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def _crumb_item_url(item: Any) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return str(item.get("@id") or item.get("id") or item.get("url") or "")
    return ""


def _json_ld_breadcrumbs(soup: BeautifulSoup) -> list[tuple[str, str]]:
    for script in soup.find_all("script", attrs={"type": re.compile(r"application/ld\+json", re.I)}):
        raw = script.string or script.get_text(strip=True)
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            continue
        for node in _walk_json(parsed):
            types = node.get("@type", [])
            if isinstance(types, str):
                types = [types]
            if not any(_normalise_label(item) == "breadcrumblist" for item in types):
                continue
            elements = node.get("itemListElement") or []
            items: list[tuple[int, str, str]] = []
            for index, element in enumerate(elements):
                if not isinstance(element, dict):
                    continue
                name = _clean_label(element.get("name"))
                item = element.get("item")
                if not name and isinstance(item, dict):
                    name = _clean_label(item.get("name"))
                if not name:
                    continue
                try:
                    position = int(element.get("position", index + 1))
                except (TypeError, ValueError):
                    position = index + 1
                items.append((position, name, _crumb_item_url(item)))
            if items:
                return [(name, url) for _, name, url in sorted(items)]
    return []


def _html_breadcrumbs(soup: BeautifulSoup) -> list[tuple[str, str]]:
    candidates = []
    for tag in soup.find_all(["nav", "ol", "ul", "div"]):
        classes = " ".join(tag.get("class") or [])
        ident = tag.get("id") or ""
        aria = tag.get("aria-label") or ""
        if "breadcrumb" in f"{classes} {ident} {aria}".lower():
            candidates.append(tag)

    for container in candidates:
        crumbs: list[tuple[str, str]] = []
        for item in container.find_all(["a", "span", "li"]):
            if item.find(["a", "span", "li"]) and item.name == "li":
                continue
            label = _clean_label(item.get_text(" ", strip=True))
            if not label or (crumbs and label == crumbs[-1][0]):
                continue
            link = item.get("href", "") if item.name == "a" else ""
            crumbs.append((label, link))
        if len(crumbs) >= 2:
            return crumbs
    return []


def _product_breadcrumb_tail(html: str) -> list[tuple[str, str]]:
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    crumbs = _json_ld_breadcrumbs(soup) or _html_breadcrumbs(soup)
    for index, (label, _) in enumerate(crumbs):
        if _normalise_label(label) in _PRODUCT_CRUMBS:
            return [(name, url) for name, url in crumbs[index + 1 :] if _clean_label(name)]
    return []


def _product_path_parts(url: str) -> list[str]:
    parts = [part for part in urlsplit(url).path.split("/") if part]
    for index, part in enumerate(parts):
        if part.lower() in _PRODUCT_SEGMENTS:
            return parts[index + 1 :]
    return []


def _upsert_family(
    families: dict[str, dict[str, Any]],
    name: str,
    url: str,
    source: str,
) -> dict[str, Any]:
    key = _normalise_label(name)
    family = families.setdefault(
        key,
        {
            "name": name,
            "url": url,
            "source": source,
            "categories": {},
        },
    )
    if url and not family["url"]:
        family["url"] = url
    if source == "breadcrumb":
        family["source"] = source
    return family


def _upsert_category(
    family: dict[str, Any],
    name: str,
    url: str,
    source: str,
) -> dict[str, Any]:
    key = _normalise_label(name)
    category = family["categories"].setdefault(
        key,
        {
            "name": name,
            "url": url,
            "source": source,
            "models": {},
            "is_leaf_product": False,
        },
    )
    if url and not category["url"]:
        category["url"] = url
    if source == "breadcrumb":
        category["source"] = source
    return category


def _add_model(
    category: dict[str, Any], name: str, url: str, source: str
) -> None:
    category["is_leaf_product"] = False
    key = _normalise_label(name)
    model = category["models"].setdefault(
        key,
        {"name": name, "url": url, "source": source},
    )
    if url and not model["url"]:
        model["url"] = url
    if source == "breadcrumb":
        model["source"] = source



_fluidcontrols_mapping = None

def _load_fluidcontrols_mapping():
    global _fluidcontrols_mapping
    if _fluidcontrols_mapping is None:
        import os, json
        path = os.path.join(os.path.dirname(__file__), "fluidcontrols_architecture.json")
        try:
            with open(path, "r") as f:
                _fluidcontrols_mapping = json.load(f)
        except Exception:
            _fluidcontrols_mapping = {}
    return _fluidcontrols_mapping

def build_product_architecture(pages: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Return Family → Category → Model data using only the crawled pages.

    A breadcrumb is the authoritative hierarchy signal.  A URL-only page is
    grouped conservatively: two-segment product URLs are placed under
    to the path hierarchy and is explicitly marked as ``url_fallback``.
    """

    families: dict[str, dict[str, Any]] = {}
    seen_urls: set[str] = set()
    unclassified_urls: list[str] = []
    source_counts = {"breadcrumb": 0, "url_fallback": 0, "ground_truth": 0}
    product_pages = 0
    
    fluid_mapping = _load_fluidcontrols_mapping()

    for page in pages:
        if int(page.get("status_code") or 0) >= 400:
            continue
        url = _canonical_url(str(page.get("url") or ""))
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        
        is_fluidcontrols = "fluidcontrols" in url
        
        # Check ground truth
        from urllib.parse import urlparse
        path = urlparse(url).path.rstrip("/")
        
        if is_fluidcontrols and path in fluid_mapping:
            mapping = fluid_mapping[path]
            product_pages += 1
            source_counts["ground_truth"] += 1
            
            family_name = mapping.get("family_name")
            family_url = mapping.get("family_url")
            family = _upsert_family(families, family_name, family_url, "ground_truth")
            
            if mapping.get("type") in ("category", "model"):
                category_name = mapping.get("category_name")
                category_url = mapping.get("category_url")
                category = _upsert_category(family, category_name, category_url, "ground_truth")
                if mapping.get("type") == "category" and mapping.get("is_leaf_product"):
                    category["is_leaf_product"] = True
                elif mapping.get("type") == "model":
                    _add_model(category, mapping.get("model_name"), mapping.get("model_url") or url, "ground_truth")
            continue

        parts = _product_path_parts(url)
        if not parts:
            continue
        product_pages += 1

        crumbs = _product_breadcrumb_tail(str(page.get("html") or ""))
        if crumbs:
            source_counts["breadcrumb"] += 1

            if len(crumbs) >= 3:
                family_name, family_url = crumbs[0]
                category_name, category_url = crumbs[1]
                model_name = crumbs[-1][0]
                family = _upsert_family(families, family_name, family_url, "breadcrumb")
                category = _upsert_category(family, category_name, category_url, "breadcrumb")
                _add_model(category, model_name, url, "breadcrumb")
            elif len(crumbs) == 2 and len(parts) >= 2:
                # Breadcrumbs prove the category and model but omit a family.
                family = _upsert_family(
                    families, "Unassigned product pages", "", "breadcrumb"
                )
                category = _upsert_category(family, crumbs[0][0], crumbs[0][1], "breadcrumb")
                _add_model(category, crumbs[1][0], url, "breadcrumb")
            elif len(crumbs) == 2:
                family = _upsert_family(families, crumbs[0][0], crumbs[0][1], "breadcrumb")
                category = _upsert_category(family, crumbs[1][0], url, "breadcrumb")
                category["is_leaf_product"] = True
            else:
                _upsert_family(families, crumbs[0][0], url, "breadcrumb")
            continue

        source_counts["url_fallback"] += 1
        if len(parts) >= 3:
            family = _upsert_family(families, _url_label(parts[0]), "", "url_fallback")
            category = _upsert_category(family, _url_label(parts[1]), "", "url_fallback")
            _add_model(category, _title_label(page), url, "url_fallback")
        elif len(parts) == 2:
            family = _upsert_family(families, _url_label(parts[0]), "", "url_fallback")
            category = _upsert_category(family, _url_label(parts[1]), url, "url_fallback")
            category["is_leaf_product"] = True
        elif len(parts) == 1:
            _upsert_family(families, _title_label(page), url, "url_fallback")
        else:
            unclassified_urls.append(url)

    output_families: list[dict[str, Any]] = []
    category_count = 0
    model_count = 0
    leaf_category_count = 0
    for family in sorted(families.values(), key=lambda item: item["name"].lower()):
        output_categories = []
        for category in sorted(family["categories"].values(), key=lambda item: item["name"].lower()):
            models = sorted(category["models"].values(), key=lambda item: item["name"].lower())
            category["models"] = models
            category_count += 1
            model_count += len(models)
            leaf_category_count += int(category["is_leaf_product"])
            output_categories.append(category)
        family["categories"] = output_categories
        output_families.append(family)

    return {
        "families": output_families,
        "unclassified_urls": sorted(unclassified_urls),
        "summary": {
            "product_pages": product_pages,
            "families": len(output_families),
            "categories": category_count,
            "model_pages": model_count,
            "leaf_categories": leaf_category_count,
            "from_breadcrumbs": source_counts["breadcrumb"],
            "from_url_fallback": source_counts["url_fallback"],
            "unclassified": len(unclassified_urls),
        },
    }
