"""AutoTeam Streamlit entry point.

Usage:
    streamlit run app/ui.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.demo.app import main  # noqa: E402

main()
