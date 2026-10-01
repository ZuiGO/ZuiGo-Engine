import mimetypes
import os
import re
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup

CONTENT_PATTERNS = {
    "pdf": (r"\.pdf($|\?|#)", "application/pdf"),
    "video": (r"\.(mp4|webm|avi|mov|mkv|wmv|flv|3gp)($|\?|#)", "video/"),
    "presentation": (r"(slideshare|docs\.google\.com/presentation|speakerdeck)", "text/html"),
    "doc": (r"\.(doc|docx|odt|rtf)($|\?|#)", "application/msword"),
    "xlsx": (r"\.(xls|xlsx|csv|ods)($|\?|#)", "application/vnd.ms-excel"),
    "image": (r"\.(jpg|jpeg|png|gif|webp|svg|avif|bmp|ico)($|\?|#)", "image/"),
    "audio": (r"\.(mp3|wav|ogg|aac|flac|wma|m4a)($|\?|#)", "audio/"),
    "archive": (r"\.(zip|tar|gz|rar|7z)($|\?|#)", "application/zip"),
}

YOUTUBE_DOMAINS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
VIMEO_DOMAINS = {"vimeo.com", "player.vimeo.com"}
GOOGLE_DOCS_DOMAINS = {"docs.google.com", "sheets.google.com", "slides.google.com"}


def classify_url(href: str) -> str | None:
    for ctype, (pattern, _) in CONTENT_PATTERNS.items():
        if re.search(pattern, href, re.IGNORECASE):
            return ctype
    parsed = urlparse(href)
    domain = parsed.netloc.lower()
    if domain in YOUTUBE_DOMAINS:
        return "video_embed"
    if domain in VIMEO_DOMAINS:
        return "video_embed"
    if domain in GOOGLE_DOCS_DOMAINS:
        path = parsed.path.lower()
        if "/document/" in path:
            return "doc"
        if "/spreadsheets/" in path:
            return "xlsx"
        if "/presentation/" in path:
            return "presentation"
    return None


def classify_with_magic(file_path: str) -> str | None:
    ext = os.path.splitext(file_path)[1].lower().lstrip(".")
    mime_map = {
        "pdf": "pdf",
        "jpg": "image", "jpeg": "image", "png": "image", "gif": "image",
        "webp": "image", "svg": "image", "avif": "image", "bmp": "image", "ico": "image",
        "mp4": "video", "webm": "video", "avi": "video", "mov": "video",
        "mkv": "video", "wmv": "video", "flv": "video",
        "mp3": "audio", "wav": "audio", "ogg": "audio", "aac": "audio", "flac": "audio",
        "doc": "doc", "docx": "doc", "odt": "doc", "rtf": "doc",
        "xls": "xlsx", "xlsx": "xlsx", "csv": "xlsx", "ods": "xlsx",
        "ppt": "presentation", "pptx": "presentation",
        "zip": "archive", "tar": "archive", "gz": "archive", "rar": "archive", "7z": "archive",
    }
    return mime_map.get(ext)


def detect_content_types(page_url: str, html: str) -> list[dict]:
    items = []
    seen = set()

    def joined(url):
        return urljoin(page_url, url.strip()) if url else ""

    def add(ctype, source_url, **extra):
        if not source_url or source_url.lower().startswith("data:"):
            return
        if source_url in seen:
            return
        seen.add(source_url)
        items.append({"type": ctype, "source_url": source_url, **extra})

    # Images via regex <img ...>
    img_regex = re.compile(r'<img\s+([^>]+)>', re.IGNORECASE)
    src_regex = re.compile(r'(?:data-lazy-src|data-src|src)\s*=\s*(["\'])(.*?)\1', re.IGNORECASE)
    alt_regex = re.compile(r'alt\s*=\s*(["\'])(.*?)\1', re.IGNORECASE)
    
    for match in img_regex.finditer(html):
        attrs = match.group(1)
        src_match = src_regex.search(attrs)
        if src_match:
            src = src_match.group(2)
            full = joined(src)
            if full:
                alt_match = alt_regex.search(attrs)
                alt_text = alt_match.group(2) if alt_match else ""
                add("image", full, alt=alt_text, tag="img")

    # Links via regex <a href="...">
    a_regex = re.compile(r'<a\s+[^>]*href\s*=\s*(["\'])(.*?)\1[^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
    for match in a_regex.finditer(html):
        href = match.group(2).strip()
        text = match.group(3)
        if not href or href.startswith("#") or href.startswith("javascript:"):
            continue
        full = joined(href)
        if not full:
            continue
        ctype = classify_url(full)
        if ctype:
            # strip tags from text
            text_clean = re.sub(r'<[^>]+>', '', text).strip()
            add(ctype, full, text=text_clean, tag="a")

    # iframes via regex
    iframe_regex = re.compile(r'<iframe\s+[^>]*src\s*=\s*(["\'])(.*?)\1', re.IGNORECASE)
    for match in iframe_regex.finditer(html):
        src = match.group(2).strip()
        full = joined(src)
        if not full:
            continue
        parsed = urlparse(full)
        domain = parsed.netloc.lower()
        is_embed = any(d in domain for d in (*YOUTUBE_DOMAINS, *VIMEO_DOMAINS))
        add("video_embed" if is_embed else "iframe", full, tag="iframe")

    # video tags
    video_regex = re.compile(r'<(?:video|audio|source)\s+[^>]*src\s*=\s*(["\'])(.*?)\1', re.IGNORECASE)
    for match in video_regex.finditer(html):
        src = match.group(2).strip()
        full = joined(src)
        if full:
            add("video", full, tag="media")

    return items
