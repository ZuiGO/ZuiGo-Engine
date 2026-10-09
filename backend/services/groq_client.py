"""Single-shot text generation via Groq, shared by the analysis services.

brand_monitor, content_growth and redirect_mapper previously imported a
non-existent ``_generate_groq`` from agent_planner. Because the analysis
pipeline wraps every stage in ``_stage(..., fallback={})`` the resulting
ImportError was swallowed and those stages silently returned nothing.
"""

from backend.config import settings
from backend.logging_setup import get_logger

logger = get_logger("groq_client")


async def generate_groq(prompt: str, max_tokens: int = 500, temperature: float = 0.2) -> str:
    """Return the model's text for ``prompt``.

    Returns ``""`` when no Groq key is configured so callers fall back to their
    deterministic defaults instead of logging an error per item. API errors
    propagate; callers already catch and log them.
    """
    if not settings.groq_api_key:
        return ""

    from groq import AsyncGroq

    from backend.services.groq_limiter import acquire_token_budget

    # Reserve prompt + completion tokens (≈4 chars/token) from the shared TPM budget.
    await acquire_token_budget(est_tokens=max_tokens + len(prompt) // 4)
    client = AsyncGroq(api_key=settings.groq_api_key)
    completion = await client.chat.completions.create(
        model=settings.groq_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return completion.choices[0].message.content or ""
