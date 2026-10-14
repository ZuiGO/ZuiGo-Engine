"""robots.txt parsing and evaluation per RFC 9309.

One implementation shared by every module that reasons about robots.txt, so
they cannot disagree. Semantics implemented:

* consecutive ``User-agent`` lines share one group; a rule line ends the group
* a crawler uses the group naming it (case-insensitive product token);
  otherwise the ``*`` group; otherwise there are no restrictions
* several groups naming the same agent are merged
* within a group the *longest* matching pattern wins; ``Allow`` wins a tie
* patterns are prefix matches supporting ``*`` and a trailing ``$``
* an empty ``Disallow:`` restricts nothing
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Rule:
    allow: bool
    pattern: str


@dataclass
class Decision:
    allowed: bool
    group: str | None = None      # agent token or "*" that supplied the rules; None = no applicable group
    rule: str | None = None       # the winning "Allow: /x" / "Disallow: /x" line, if any
    restricted_patterns: list[str] = field(default_factory=list)  # all Disallow patterns of the group


class RobotsRules:
    def __init__(self, groups: dict[str, list[Rule]]):
        self._groups = groups  # lower-cased agent token -> merged rules

    @property
    def agents(self) -> list[str]:
        return sorted(self._groups)

    def check(self, agent: str, path: str = "/") -> Decision:
        token = (agent or "").strip().lower()
        group = token if token in self._groups else ("*" if "*" in self._groups else None)
        if group is None:
            return Decision(allowed=True)
        rules = self._groups[group]
        restricted = [r.pattern for r in rules if not r.allow]
        best: Rule | None = None
        for r in rules:
            if _matches(r.pattern, path):
                if best is None or len(r.pattern) > len(best.pattern) or (
                    len(r.pattern) == len(best.pattern) and r.allow and not best.allow
                ):
                    best = r
        if best is None:
            return Decision(allowed=True, group=group, restricted_patterns=restricted)
        return Decision(
            allowed=best.allow,
            group=group,
            rule=f"{'Allow' if best.allow else 'Disallow'}: {best.pattern}",
            restricted_patterns=restricted,
        )


def parse_robots(text: str | None) -> RobotsRules:
    groups: dict[str, list[Rule]] = {}
    current: list[str] = []
    last_was_agent = False
    for raw in (text or "").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field_name, value = line.split(":", 1)
        field_name = field_name.strip().lower()
        value = value.strip()
        if field_name == "user-agent":
            token = value.lower()
            if not last_was_agent:
                current = []
            if token:
                current.append(token)
                groups.setdefault(token, [])
            last_was_agent = True
            continue
        last_was_agent = False
        if field_name in ("allow", "disallow") and current:
            if not value:
                continue  # empty Disallow = nothing restricted; empty Allow = no-op
            for token in current:
                groups[token].append(Rule(allow=(field_name == "allow"), pattern=value))
    return RobotsRules(groups)


def _matches(pattern: str, path: str) -> bool:
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    regex = "".join(".*" if ch == "*" else re.escape(ch) for ch in body)
    return re.match(regex + ("$" if anchored else ""), path or "/") is not None


# --------------------------------------------------------------------------
# Reference list of AI crawlers. This is maintained *reference data* (names are
# published by each vendor), not a measurement - review it periodically.
# purpose: "training" = collects data for model training (blocking is a policy
# choice, not a defect); "search" / "user" = fetches pages to answer a user's
# query (blocking these makes the site uncitable by that product).
# --------------------------------------------------------------------------
AI_CRAWLERS: list[tuple[str, str, str]] = [
    ("OAI-SearchBot", "OpenAI (ChatGPT search)", "search"),
    ("ChatGPT-User", "OpenAI (ChatGPT browsing)", "user"),
    ("GPTBot", "OpenAI (training)", "training"),
    ("Claude-SearchBot", "Anthropic (Claude search)", "search"),
    ("Claude-User", "Anthropic (Claude browsing)", "user"),
    ("ClaudeBot", "Anthropic (training)", "training"),
    ("anthropic-ai", "Anthropic (legacy training agent)", "training"),
    ("PerplexityBot", "Perplexity (search index)", "search"),
    ("Perplexity-User", "Perplexity (browsing)", "user"),
    ("Google-Extended", "Google (Gemini training/grounding control)", "training"),
    ("Applebot-Extended", "Apple (training control)", "training"),
    ("Meta-ExternalAgent", "Meta (training)", "training"),
    ("CCBot", "Common Crawl (training corpus)", "training"),
    ("Bytespider", "ByteDance (training)", "training"),
]
ANSWER_ENGINE_PURPOSES = {"search", "user"}
