"""The domain-agent swarm must actually be wired into planning and dispatch.

Regressions covered:
- BaseAgent overrode a method AgentRuntime never called and imported planner
  helpers that don't exist, so role prompts / tool restrictions were ignored.
- The arq worker always built a bare AgentRuntime, ignoring run.agent_type.
- run_single_page_analysis / query_knowledge tools imported missing functions.
- apply_approved_changes tool reported success even when the route said ok=False.
"""

import types

import pytest

from backend.models.agent_schemas import AgentDecision
from backend.services import agent_planner
from backend.services.agent_swarm import AGENT_CONFIGS, BaseAgent, build_agent_for_run
from backend.services.agent_tools import TOOL_REGISTRY


# ---------------------------------------------------------------- planner ----

def test_every_swarm_tool_exists_in_registry():
    for domain, cfg in AGENT_CONFIGS.items():
        missing = [t for t in cfg["allowed_tools"] if t not in TOOL_REGISTRY]
        assert not missing, f"{domain} references unknown tools: {missing}"


def test_tools_json_filters_to_allowed():
    import json

    names = {t["name"] for t in json.loads(agent_planner._tools_json(["crawl_urls", "read_current_state"]))}
    assert names == {"crawl_urls", "read_current_state"}
    assert len(json.loads(agent_planner._tools_json())) == len(TOOL_REGISTRY)


def test_validate_decision_rejects_disallowed_tool():
    payload = {"reasoning": "x", "tool": "run_analyzers", "args": {}}
    assert agent_planner._validate_decision(payload, {}, allowed_tools=["crawl_urls"]) is None
    assert agent_planner._validate_decision(payload, {}, allowed_tools=["run_analyzers"]) is not None
    assert agent_planner._validate_decision(payload, {}) is not None  # unrestricted


def test_complete_is_always_allowed():
    payload = {"reasoning": "done", "tool": "complete"}
    assert agent_planner._validate_decision(payload, {}, allowed_tools=["crawl_urls"]).tool == "complete"


@pytest.mark.asyncio
async def test_fallback_for_restricted_agent_completes_instead_of_leaking_tools(monkeypatch):
    monkeypatch.setattr(agent_planner.settings, "groq_api_key", "")
    # Fallback wants crawl_urls first; a report agent may not crawl.
    decision = await agent_planner.decide({"facts": {}, "urls": ["https://x.example"]}, allowed_tools=["generate_pdf_report"])
    assert decision.tool == "complete"
    # ...but a crawl agent gets the crawl.
    decision = await agent_planner.decide({"facts": {}, "urls": ["https://x.example"]}, allowed_tools=["crawl_urls"])
    assert decision.tool == "crawl_urls"


@pytest.mark.asyncio
async def test_llm_prompt_includes_role_prefix_and_only_allowed_tools(monkeypatch):
    captured = {}

    class FakeCompletions:
        async def create(self, **kw):
            captured.update(kw)
            msg = types.SimpleNamespace(content='{"reasoning": "r", "tool": "complete", "args": {}}')
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)])

    class FakeClient:
        def __init__(self, api_key):
            self.chat = types.SimpleNamespace(completions=FakeCompletions())

    import groq

    monkeypatch.setattr(groq, "AsyncGroq", FakeClient)
    monkeypatch.setattr(agent_planner.settings, "groq_api_key", "k")

    await agent_planner.decide(
        {"domain": "x.com", "goal": "g", "facts": {}},
        allowed_tools=["crawl_urls"],
        system_prefix="You are the Crawl Agent.",
    )
    system = captured["messages"][0]["content"]
    assert system.startswith("You are the Crawl Agent.")
    assert '"name": "crawl_urls"' in system
    assert '"name": "run_analyzers"' not in system


# ------------------------------------------------------------- BaseAgent ----

@pytest.mark.asyncio
async def test_base_agent_plans_with_its_own_tools_and_prompt(monkeypatch):
    from backend.services.agent_swarm import base_agent

    seen = {}

    async def fake_decide(state, *, allowed_tools=None, system_prefix=""):
        seen.update(allowed_tools=allowed_tools, system_prefix=system_prefix)
        return AgentDecision(reasoning="", tool="complete")

    monkeypatch.setattr(base_agent, "decide", fake_decide)
    agent = BaseAgent(job_id="j1", allowed_tools=["crawl_urls"], system_prompt="ROLE")
    # AgentRuntime._decide_with_guard is what the run loop actually calls.
    decision = await agent._decide_with_guard(
        {"goal": "g", "domain": "x.com", "urls": [], "steps": [], "facts": {}}
    )
    assert decision.tool == "complete"
    assert seen == {"allowed_tools": ["crawl_urls"], "system_prefix": "ROLE"}


def test_build_agent_for_run_resolves_agent_type():
    crawl = build_agent_for_run({"agent_type": "crawl", "job_id": "j1"})
    assert crawl.allowed_tools == AGENT_CONFIGS["crawl"]["allowed_tools"]
    assert crawl.job_id == "j1"

    for doc in ({"agent_type": "does-not-exist", "job_id": "j"}, {"job_id": "j"}, {}):
        agent = build_agent_for_run(doc)
        assert agent.allowed_tools == AGENT_CONFIGS["coordinator"]["allowed_tools"]


@pytest.mark.asyncio
async def test_worker_agent_run_dispatches_by_agent_type(monkeypatch):
    from backend import worker

    started = {}

    async def fake_find_one(q):
        return {"id": q["id"], "agent_type": "report", "job_id": "job-9"}

    fake_db = types.SimpleNamespace(agent_runs=types.SimpleNamespace(find_one=fake_find_one))
    monkeypatch.setattr("backend.db.mongo.get_db", lambda: fake_db)

    async def fake_start(self, run_id):
        started["agent"] = self
        started["run_id"] = run_id

    monkeypatch.setattr(BaseAgent, "start", fake_start)

    await worker.agent_run({}, "run-1")
    assert started["run_id"] == "run-1"
    assert isinstance(started["agent"], BaseAgent)
    assert started["agent"].allowed_tools == AGENT_CONFIGS["report"]["allowed_tools"]


# ------------------------------------------------------------ domain tools ----

@pytest.mark.asyncio
async def test_single_page_tool_uses_real_service_and_drops_screenshots(monkeypatch):
    from backend.services.agent_tools import domain_tools

    async def fake_cmp(job_id, url):
        return {"fields": [{"field": "title"}], "visuals": {"baseline_b64": "A" * 50000}}

    monkeypatch.setattr("backend.services.single_page_service.generate_visual_comparison", fake_cmp)
    result = await domain_tools._run_single_page_analysis_tool("https://x.example", "j1")
    assert result["ok"] is True
    assert "visuals" not in result["comparison"]
    assert result["comparison"]["fields"] == [{"field": "title"}]


@pytest.mark.asyncio
async def test_single_page_tool_reports_failures(monkeypatch):
    from backend.services.agent_tools import domain_tools

    async def boom(job_id, url):
        raise RuntimeError("playwright died")

    monkeypatch.setattr("backend.services.single_page_service.generate_visual_comparison", boom)
    result = await domain_tools._run_single_page_analysis_tool("https://x.example", "j1")
    assert result == {"ok": False, "error": "playwright died"}


@pytest.mark.asyncio
async def test_query_knowledge_tool_reads_memory(monkeypatch):
    from backend.services.agent_tools import domain_tools

    async def fake_facts(domain):
        return {"domain_facts": {"insights": {"clicks": 5}}, "pages_seen": 3}

    async def fake_eps(domain, limit=5):
        return [{"id": "e1"}]

    monkeypatch.setattr("backend.services.agent_memory.get_facts", fake_facts)
    monkeypatch.setattr("backend.services.agent_memory.recent_episodes", fake_eps)
    out = await domain_tools._query_knowledge_tool("j1", "x.com", "what do we know?")
    assert out["facts_summary"] == {"insights": {"clicks": 5}}
    assert out["other_facts"] == {"pages_seen": 3}
    assert out["recent_episodes"] == [{"id": "e1"}]


@pytest.mark.asyncio
async def test_apply_tool_propagates_route_failure(monkeypatch):
    from backend.services.agent_tools import domain_tools

    async def no_token(job_id):
        return {"ok": False, "reason": "no_token", "message": "No GitHub token configured."}

    monkeypatch.setattr("backend.routes.actions.apply_approved_changes", no_token)
    result = await domain_tools._apply_approved_changes_tool("j1")
    assert result["ok"] is False
    assert result["reason"] == "no_token"
