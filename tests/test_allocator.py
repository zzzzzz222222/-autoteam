from app.allocator import role_allocator
from app.allocator.role_allocator import RoleAllocator
from app.analyzer.task_analyzer import TaskAnalyzer
from app.models.capability import CapabilityName
from app.models.task import ComplexityLevel, Task, TaskAnalysis


def test_all_required_capabilities_are_covered() -> None:
    analysis = TaskAnalysis(
        complexity=ComplexityLevel.MEDIUM,
        required_capabilities=[
            CapabilityName.MARKET_RESEARCH,
            CapabilityName.DATA_ANALYSIS,
            CapabilityName.REPORT_WRITING,
        ],
        reasoning="test",
    )
    agents = RoleAllocator().allocate(analysis)
    covered = {capability for agent in agents for capability in agent.role.capabilities}
    assert set(analysis.required_capabilities).issubset(covered)


def test_roles_are_unique_and_templates_cover_multiple_capabilities() -> None:
    analysis = TaskAnalysis(
        complexity=ComplexityLevel.LOW,
        required_capabilities=[CapabilityName.MARKET_RESEARCH, CapabilityName.DATA_ANALYSIS],
        reasoning="test",
    )
    agents = RoleAllocator().allocate(analysis)
    assert len({agent.role.name for agent in agents}) == len(agents)
    assert any(len(agent.role.capabilities) > 1 for agent in agents)


def test_missing_template_creates_general_agent(monkeypatch: object) -> None:
    monkeypatch.setattr(role_allocator, "ROLE_TEMPLATES", [])
    analysis = TaskAnalysis(
        complexity=ComplexityLevel.LOW,
        required_capabilities=[CapabilityName.FACT_CHECKING],
        reasoning="test",
    )
    agents = RoleAllocator().allocate(analysis)
    assert agents[0].role.name == "General Agent"


def test_coding_task_includes_developer() -> None:
    analysis = TaskAnalyzer().analyze(Task(description="实现 Python 接口"))
    assert "Developer" in {agent.role.name for agent in RoleAllocator().allocate(analysis)}


def test_research_task_has_reasonable_role() -> None:
    analysis = TaskAnalyzer().analyze(Task(description="研究市场和竞争对手"))
    names = {agent.role.name for agent in RoleAllocator().allocate(analysis)}
    assert {"Market Researcher", "Competitor Analyst"}.intersection(names)
