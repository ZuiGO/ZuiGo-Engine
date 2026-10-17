from backend.logging_setup import get_logger
from backend.models.agent_schemas import AgentDecision
from backend.services.agent_planner import decide
from backend.services.agent_runtime import AgentRuntime

logger = get_logger("base_agent")


class BaseAgent(AgentRuntime):
    """A domain-specialised agent.

    Reuses AgentRuntime's loop, budgets, approval checkpoints and loop guards,
    but plans with its own role prompt and a restricted tool menu.
    """

    def __init__(self, job_id: str, allowed_tools: list[str], system_prompt: str):
        super().__init__()
        self.job_id = job_id
        self.allowed_tools = allowed_tools
        self.system_prompt = system_prompt

    async def _decide(self, state: dict) -> AgentDecision:
        # The planner both offers only allowed_tools to the LLM and rejects any
        # decision outside them, so the role prompt/tool restriction is real
        # rather than decorative.
        return await decide(
            state,
            allowed_tools=self.allowed_tools,
            system_prefix=self.system_prompt,
        )
