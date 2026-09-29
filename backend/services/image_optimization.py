"""Image optimization audit (offline, crawl-derived).

Measures the share of crawled <img> elements using modern formats (WebP/AVIF
via src or <picture><source>), lazy loading, and explicit dimensions — the
measurable parts of the seo-audit skill's Image Optimization checklist.
"""

from datetime import datetime

from bs4 import BeautifulSoup
from urllib.parse import urljoin

from backend.db.mongo import get_db
from backend.logging_setup import get_logger

logger = get_logger("image_optimization")

MODERN_EXT = {".webp", ".avif"}


def _resolve(page_url: str, src: str) -> str:
    if not src:
        return ""
    if src.lower().startswith("data:"):
        return ""
    full = urljoin(page_url, src.strip())
    if full.lower().startswith("data:"):
        return ""
    return full


async def audit_image_optimization(job_id: str) -> dict:
    db = get_db()
    pages = await db.pages.find({"job_id": job_id}, {"html": 1, "url": 1}).to_list(length=None)

    total_imgs = 0
    modern_imgs = 0
    lazy_imgs = 0
    dims_missing = 0
    alt_missing = 0
    pages_with_imgs = 0
    occurrences = 0
    seen: set[str] = set()

    alt_missing_urls = []
    dims_missing_urls = []
    legacy_format_urls = []
    non_lazy_urls = []

    images = {}

    for p in pages:
        html = p.get("html") or ""
        if not html:
            continue
        soup = BeautifulSoup(html, "lxml")
        imgs = soup.find_all("img")
        if not imgs:
            continue
        pages_with_imgs += 1
        occurrences += len(imgs)
        for img in imgs:
            src = (img.get("src") or "").strip()
            key = _resolve(p.get("url", ""), src)
            if not key:
                continue
            
            if key not in images:
                images[key] = {
                    "alt_missing": False,
                    "lazy": False,
                    "modern": False,
                    "dims_missing": False,
                }
                
            state = images[key]
            
            if not img.has_attr("alt"):
                state["alt_missing"] = True
                
            loading = (img.get("loading") or "").strip().lower()
            if loading == "lazy":
                state["lazy"] = True
                
            srcset = (img.get("srcset") or "").strip().lower()
            if any(key.lower().endswith(ext) or ext in srcset for ext in MODERN_EXT):
                state["modern"] = True
            else:
                picture = next(
                    (a for a in (img.parents if img.parent is not None else iter(()))
                     if getattr(a, "name", "") == "picture"),
                    None,
                )
                if picture is not None:
                    sources = picture.find_all("source")
                    if any((s.get("type") or "").lower() in ("image/webp", "image/avif") for s in sources):
                        state["modern"] = True
                        
            if not (img.get("width") and img.get("height")):
                state["dims_missing"] = True

    total_imgs = len(images)
    for key, state in images.items():
        if state["alt_missing"]:
            alt_missing += 1
            if len(alt_missing_urls) < 20: alt_missing_urls.append(key)
        if state["lazy"]:
            lazy_imgs += 1
        elif len(non_lazy_urls) < 20:
            non_lazy_urls.append(key)
        if state["modern"]:
            modern_imgs += 1
        elif len(legacy_format_urls) < 20:
            legacy_format_urls.append(key)
        if state["dims_missing"]:
            dims_missing += 1
            if len(dims_missing_urls) < 20: dims_missing_urls.append(key)

    total = max(total_imgs, 1)
    modern_share = modern_imgs / total if total_imgs else 0
    lazy_share = lazy_imgs / total if total_imgs else 0
    dim_share = dims_missing / total if total_imgs else 0
    alt_share = alt_missing / total if total_imgs else 0

    subscores = {
        "modern_formats": 40 if modern_share >= 0.7 else 20 if modern_share > 0 else 15 if total_imgs else 40,
        "lazy_loading": 30 if lazy_share >= 0.5 else 10 if lazy_imgs else 0,
        "dimensions": 30 if dim_share <= 0.3 else 0,
    }
    score = sum(subscores.values())

    checks = [
        {
            "passed": modern_share >= 0.7,
            "label": "Modern image formats (WebP/AVIF)",
            "detail": (f"{modern_imgs} of {total_imgs} unique image(s) use WebP/AVIF."
                       if total_imgs else "No images found to evaluate."),
            "evidence": legacy_format_urls
        },
        {
            "passed": lazy_share >= 0.5,
            "label": "Lazy loading on below-the-fold images",
            "detail": f"{lazy_imgs} of {total_imgs} unique image(s) load lazily.",
            "evidence": non_lazy_urls
        },
        {
            "passed": dim_share <= 0.3,
            "label": "Width/height attributes set (CLS reduction)",
            "detail": f"{dims_missing} of {total_imgs} unique image(s) lack explicit dimensions.",
            "evidence": dims_missing_urls
        },
        {
            "passed": alt_share <= 0.3,
            "label": "Descriptive alt text on images",
            "detail": f"{alt_missing} of {total_imgs} unique image(s) are missing alt text.",
            "evidence": alt_missing_urls
        },
    ]

    summary = {
        "job_id": job_id,
        "score": score,
        "subscores": subscores,
        "checks": checks,
        "total_images": total_imgs,
        "image_occurrences": occurrences,
        "modern_images": modern_imgs,
        "lazy_images": lazy_imgs,
        "missing_dimensions": dims_missing,
        "missing_alt": alt_missing,
        "pages_with_images": pages_with_imgs,
        "modern_share": round(modern_share, 3),
        "lazy_share": round(lazy_share, 3),
        "dimensions_share": round(dim_share, 3),
        "alt_share": round(alt_share, 3),
        "generated_at": datetime.utcnow(),
    }
    await db.image_optimization_audits.update_one(
        {"job_id": job_id},
        {"$set": summary},
        upsert=True,
    )
    logger.info("Image optimization job=%s score=%s images=%s", job_id, score, total_imgs)
    return summary