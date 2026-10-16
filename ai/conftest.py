"""pytest setup for the AI tests: make the ai/ modules and the backend's flat modules importable."""
import sys
from pathlib import Path

AI_DIR = Path(__file__).resolve().parent
BACKEND_DIR = AI_DIR.parent / "backend"

for path in (BACKEND_DIR, AI_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))