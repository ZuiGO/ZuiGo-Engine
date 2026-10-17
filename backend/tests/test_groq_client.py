"""Shared Groq helper + the services that depend on it.

Regression: brand_monitor / content_growth / redirect_mapper imported a
non-existent ``_generate_groq``; the pipeline's ``_stage`` swallowed the
ImportError so those stages silently produced nothing.
"""

import asyncio
import importlib
import types

import pytest

from backend.services import groq_client, groq_limiter


@pytest.mark.parametrize(
    "module", ["brand_monitor", "content_growth", "redirect_mapper"]
)
def test_dependent_services_import(module):
    importlib.import_module(f"backend.services.{module}")


@pytest.mark.asyncio
async def test_returns_empty_string_without_api_key(monkeypatch):
    monkeypatch.setattr(groq_client.settings, "groq_api_key", "")
    assert await groq_client.generate_groq("hi") == ""


@pytest.mark.asyncio
async def test_calls_groq_with_given_params(monkeypatch):
    seen = {}

    class FakeCompletions:
        async def create(self, **kw):
            seen.update(kw)
            msg = types.SimpleNamespace(content='{"ok": true}')
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)])

    class FakeClient:
        def __init__(self, api_key):
            self.chat = types.SimpleNamespace(completions=FakeCompletions())

    async def no_wait(est_tokens=0):
        seen["est"] = est_tokens

    import groq

    monkeypatch.setattr(groq, "AsyncGroq", FakeClient)
    monkeypatch.setattr(groq_limiter, "acquire_token_budget", no_wait)
    monkeypatch.setattr(groq_client.settings, "groq_api_key", "k")
    monkeypatch.setattr(groq_client.settings, "groq_model", "m")

    out = await groq_client.generate_groq("prompt", max_tokens=150, temperature=0.1)
    assert out == '{"ok": true}'
    assert seen["model"] == "m"
    assert seen["max_tokens"] == 150
    assert seen["temperature"] == 0.1
    assert seen["messages"] == [{"role": "user", "content": "prompt"}]
    assert seen["est"] >= 150


@pytest.mark.asyncio
async def test_limiter_does_not_hang_on_oversized_request():
    groq_limiter._used = 0.0
    groq_limiter._window_start = 0.0
    # Would previously sleep forever: estimate larger than the whole TPM budget.
    await asyncio.wait_for(
        groq_limiter.acquire_token_budget(groq_limiter.TOKEN_BUDGET * 3), timeout=2
    )

