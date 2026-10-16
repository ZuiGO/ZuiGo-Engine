"""Policy thresholds and finding classification for the SEO analyzer.

Nothing here is a *measurement*. These are the explicit, reviewable decisions
that turn measured page facts into findings. They live in one module so they can
be read, tuned and tested - and every finding states the numbers it used in its
``evidence`` so a reader can see exactly why it fired.

``basis`` says how a finding was derived (replaces the old hand-written
``confidence`` numbers, which were constants and measured nothing):

* ``measured``  - a direct fact read from the page/response (e.g. "no <title>")
* ``rule``      - a measured value compared with a documented threshold (e.g. thin content)
* ``heuristic`` - a pattern-based judgement that can be wrong (e.g. hostname looks like staging)
"""

from __future__ import annotations

import ipaddress
import re

# --- thresholds (policy) ---------------------------------------------------
TITLE_MIN_CHARS = 30    # shorter titles rarely describe the page
TITLE_MAX_CHARS = 60    # Google truncates by pixel width (~600px); ~60 chars is the usual limit
META_MIN_CHARS = 50
META_MAX_CHARS = 160   # search results usually truncate descriptions beyond ~160 chars
ALT_MIN_CHARS = 8
IMAGE_OVERSIZED_BYTES = 200_000
DOC_OVERSIZED_BYTES = 5_000_000
GENERIC_THIN_WORDS = 350
THIN_WORDS_BY_TYPE = (  # (page_type substrings, minimum main-content words)
    (("product", "item"), 150),
    (("industry", "category"), 700),
    (("legal", "utility"), 50),
)
DEEP_CLICK_DEPTH = 3          # pages deeper than this many clicks are "deep"
LONG_REDIRECT_CHAIN = 3       # hops


def thin_threshold(page_type: str | None) -> int:
    pt = (page_type or "").lower()
    for needles, minimum in THIN_WORDS_BY_TYPE:
        if any(n in pt for n in needles):
            return minimum
    return GENERIC_THIN_WORDS


def is_thin(page: dict) -> tuple[bool, int]:
    """(is_thin, minimum_words) - the single definition used by the analyzer AND site health."""
    minimum = thin_threshold(page.get("page_type"))
    return (page.get("word_count") or 0) < minimum, minimum


def is_error_page(page: dict) -> bool:
    return (page.get("status_code") or 200) >= 400


# --- staging / non-production hostname detection -----------------------------
NON_PROD_LABELS = {"staging", "stage", "stg", "dev", "develop", "development", "test", "testing", "qa", "uat", "sandbox", "preview"}
_SECOND_LEVEL = {"co", "com", "org", "net", "gov", "ac", "edu", "ltd", "plc", "or", "ne"}


def staging_label(host: str) -> str | None:
    """The non-production label in the *sub*domain of ``host`` (e.g. 'dev' in dev.example.com).

    Only whole dot/hyphen-separated tokens of subdomain labels count, so 'developer.mozilla.org',
    'latest-news.com' or 'contest.in' do not match. IPs and localhost never match.
    """
    host = (host or "").lower().split(":")[0].strip(".")
    if not host or host == "localhost":
        return None
    try:
        ipaddress.ip_address(host)
        return None
    except ValueError:
        pass
    labels = host.split(".")
    if len(labels) < 3:
        return None  # no subdomain
    registrable = 3 if (labels[-2] in _SECOND_LEVEL and len(labels[-1]) == 2) else 2
    for label in labels[:-registrable]:
        for token in re.split(r"[-_]", label):
            if token in NON_PROD_LABELS:
                return token
    return None


# --- finding basis -------------------------------------------------------------
_MEASURED = {
    "page_http_error", "title_missing", "title_duplicate", "meta_description_missing",
    "meta_description_duplicate", "h1_missing", "h1_multiple", "noindex_page", "no_structured_data",
    "image_alt_missing", "page_images_missing_alt", "pdf_no_text_layer", "document_extraction_failed",
    "video_self_hosted",
}
_RULE = {
    "thin_content", "title_too_short", "title_too_long", "meta_description_short",
    "image_oversized", "document_oversized", "image_alt_is_filename",
}
# everything else (staging_leakage, entity_coverage_low, keyword_cannibalization, aeo_*, eaat_*,
# no_extractable_format, image_alt_generic, ...) is a heuristic.


def basis_for(issue_key: str) -> str:
    if issue_key in _MEASURED:
        return "measured"
    if issue_key in _RULE:
        return "rule"
    return "heuristic"
