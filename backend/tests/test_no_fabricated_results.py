"""Static guard: results must come from measurements, never from invented defaults.

These patterns are exactly how fabricated data crept in before (a missing measurement quietly
becoming a perfect score, or a made-up 'after' value). If one of these tests fails, return None
("not measured") instead of a stand-in value.
"""

import re
from pathlib import Path

import backend

ROOT = Path(list(backend.__path__)[0])
SOURCES = [p for p in ROOT.rglob("*.py") if "tests" not in p.relative_to(ROOT).parts]

FORBIDDEN = {
    r"""\.get\(\s*["']\w*score\w*["']\s*,\s*100\s*\)""": "a missing score defaulting to 100",
    r"^\s*score\s*=\s*100\s*$": "a score that starts perfect and is reduced by invented penalties",
    r"old_vitals\s*=\s*\d+": "a hard-coded fallback for Core Web Vitals",
    r"old_vitals\s*\+\s*\d+": "an invented 'improved' Core Web Vitals value",
    r"sitemap_coverage\s*=\s*100": "missing sitemap data assumed to be fully covered",
}


def test_no_fabricated_result_patterns():
    hits = []
    for path in SOURCES:
        text = path.read_text()
        for pattern, why in FORBIDDEN.items():
            for m in re.finditer(pattern, text, re.M):
                line = text.count("\n", 0, m.start()) + 1
                hits.append(f"{path.relative_to(ROOT.parent)}:{line}  {why}")
    assert not hits, "fabricated-result patterns found:\n" + "\n".join(hits)


def test_no_hand_written_confidence_numbers_in_findings():
    text = (ROOT / "services" / "seo_analyzer.py").read_text()
    assert not re.search(r'"confidence"\s*:\s*[0-9.]+', text)
