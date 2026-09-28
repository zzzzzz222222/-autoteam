from app.analyzer.task_analyzer import TaskAnalyzer
from app.models.capability import CapabilityName
from app.models.task import ComplexityLevel, Task


def test_industry_competition_detects_research_and_competitor_analysis() -> None:
    analysis = TaskAnalyzer().analyze(Task(description="分析行业竞争"))
    assert CapabilityName.MARKET_RESEARCH in analysis.required_capabilities
    assert CapabilityName.COMPETITOR_ANALYSIS in analysis.required_capabilities


def test_complex_task_is_high_complexity() -> None:
    analysis = TaskAnalyzer().analyze(
        Task(description="分析市场竞争、财务数据、行业风险，并生成研究报告")
    )
    assert analysis.complexity is ComplexityLevel.HIGH


def test_no_llm_uses_rule_analysis() -> None:
    assert TaskAnalyzer().analyze(Task(description="写 Python 代码")).confidence == 0.5


def test_llm_failure_falls_back() -> None:
    class BrokenLLM:
        def structured_completion(self, prompt: str, response_model: object) -> object:
            raise RuntimeError("unavailable")

    analysis = TaskAnalyzer(BrokenLLM()).analyze(Task(description="市场趋势"))
    assert CapabilityName.MARKET_RESEARCH in analysis.required_capabilities


def test_unknown_task_falls_back_to_planning() -> None:
    analysis = TaskAnalyzer().analyze(Task(description="做点神秘的事情"))
    assert analysis.required_capabilities == [CapabilityName.TASK_PLANNING]
