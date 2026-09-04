import pytest
from backend.models.agent_schemas import AgentRun, AgentDecision
from backend.services.agent_swarm import get_agent_for_domain

@pytest.fixture
def mock_run():
    return AgentRun(id="r1", goal="improve", domain="x.com", job_id="j1", urls=["https://x.com"])

class TestDomainAgents:
    def test_action_agent_init(self):
        agent = get_agent_for_domain("action")(job_id="j1")
        assert "Action" in agent.system_prompt
        assert "apply_approved_changes" in agent.allowed_tools

    def test_analysis_agent_init(self):
        agent = get_agent_for_domain("analysis")(job_id="j1")
        assert "Analysis" in agent.system_prompt
        assert "run_analyzers" in agent.allowed_tools
        assert "run_single_page_analysis" in agent.allowed_tools

    def test_competitor_agent_init(self):
        agent = get_agent_for_domain("competitor")(job_id="j1")
        assert "Competitor" in agent.system_prompt
        assert "run_competitor_audit" in agent.allowed_tools

    def test_crawl_agent_init(self):
        agent = get_agent_for_domain("crawl")(job_id="j1")
        assert "Crawl" in agent.system_prompt
        assert "crawl_urls" in agent.allowed_tools

    def test_insight_agent_init(self):
        agent = get_agent_for_domain("insight")(job_id="j1")
        assert "Insight" in agent.system_prompt
        assert "fetch_seo_insights" in agent.allowed_tools

    def test_report_agent_init(self):
        agent = get_agent_for_domain("report")(job_id="j1")
        assert "Report" in agent.system_prompt
        assert "generate_pdf_report" in agent.allowed_tools

    def test_schedule_agent_init(self):
        agent = get_agent_for_domain("schedule")(job_id="j1")
        assert "Schedule" in agent.system_prompt
        assert "create_schedule" in agent.allowed_tools

    def test_technical_agent_init(self):
        agent = get_agent_for_domain("technical")(job_id="j1")
        assert "Technical" in agent.system_prompt
        assert "audit_technical" in agent.allowed_tools
