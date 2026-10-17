import pytest

from backend.services.robots_rules import AI_CRAWLERS, parse_robots


def allowed(text, agent, path="/"):
    return parse_robots(text).check(agent, path).allowed


def test_wildcard_block_applies_to_agents_without_own_group():
    assert allowed("User-agent: *\nDisallow: /", "GPTBot") is False


def test_specific_group_overrides_wildcard():
    t = "User-agent: *\nDisallow: /\n\nUser-agent: GPTBot\nAllow: /\n"
    assert allowed(t, "GPTBot") is True
    assert allowed(t, "ClaudeBot") is False


def test_consecutive_user_agent_lines_share_one_group():
    t = "User-agent: GPTBot\nUser-agent: ClaudeBot\nDisallow: /\n"
    assert allowed(t, "GPTBot") is False
    assert allowed(t, "ClaudeBot") is False
    assert allowed(t, "PerplexityBot") is True  # no group, no '*'


def test_path_specific_disallow_does_not_block_root():
    t = "User-agent: GPTBot\nDisallow: /private/\n"
    d = parse_robots(t).check("GPTBot", "/")
    assert d.allowed is True and d.restricted_patterns == ["/private/"]
    assert parse_robots(t).check("GPTBot", "/private/x").allowed is False


def test_longest_match_wins_and_allow_wins_ties():
    t = "User-agent: *\nDisallow: /docs/\nAllow: /docs/public/\n"
    r = parse_robots(t)
    assert r.check("x", "/docs/secret").allowed is False
    assert r.check("x", "/docs/public/a").allowed is True
    tie = parse_robots("User-agent: *\nDisallow: /a\nAllow: /a\n")
    assert tie.check("x", "/a").allowed is True


def test_wildcards_and_end_anchor():
    r = parse_robots("User-agent: *\nDisallow: /*.pdf$\n")
    assert r.check("x", "/files/a.pdf").allowed is False
    assert r.check("x", "/files/a.pdf?x=1").allowed is True


def test_empty_disallow_and_empty_file_allow_everything():
    assert allowed("User-agent: *\nDisallow:\n", "GPTBot") is True
    assert allowed("", "GPTBot") is True
    assert allowed(None, "GPTBot") is True


def test_case_insensitive_and_comments():
    t = "# hi\nUSER-AGENT: gptbot  # the bot\nDISALLOW: /\n"
    assert allowed(t, "GPTBot") is False


def test_reference_list_is_well_formed():
    names = [n.lower() for n, _, _ in AI_CRAWLERS]
    assert len(names) == len(set(names))
    assert {p for _, _, p in AI_CRAWLERS} == {"search", "user", "training"}
