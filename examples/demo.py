import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from main import format_result

DEMOS = [
    ("Demo 1 — Research", "分析新能源汽车行业竞争格局并生成投资研究报告"),
    ("Demo 2 — Coding", "实现一个 FastAPI 用户认证模块，并编写单元测试"),
    ("Demo 3 — Planning", "制定一个新产品从需求分析到上线的执行计划，并分析潜在风险"),
]


def main() -> None:
    for title, task in DEMOS:
        print(f"\n{title}")
        print(format_result(task))


if __name__ == "__main__":
    main()
