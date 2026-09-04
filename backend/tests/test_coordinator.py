import pytest
from backend.services.agent_swarm import get_agent_for_domain

class TestCoordinatorAgent:
    def test_coordinator_init(self):
        agent = get_agent_for_domain("coordinator")(job_id="j1")
        assert agent.job_id == "j1"
        assert "delegate_to_domain_agent" in agent.allowed_tools
        assert "read_current_state" in agent.allowed_tools
        
    def test_coordinator_prompt(self):
        agent = get_agent_for_domain("coordinator")(job_id="j1")
        prompt = agent.system_prompt
        assert "Coordinator Orchestrator Agent" in prompt
        assert "crawl" in prompt
        assert "analysis" in prompt
        assert "delegate_to_domain_agent" in prompt
