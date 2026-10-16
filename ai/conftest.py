"""pytest setup for the AI tests: make the ai/ modules importable (the backend is imported as `backend.*`)."""
import sys
from pathlib import Path

AI_DIR = Path(__file__).resolve().parent
REPO_ROOT = AI_DIR.parent

for path in (REPO_ROOT, AI_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))