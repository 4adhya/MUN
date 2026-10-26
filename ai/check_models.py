"""Which models work with my key? Run from the repo root: python ai/check_models.py"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai.check_gemini import REPO_ROOT, get_api_key, load_env_file, redact
from google import genai

load_env_file(REPO_ROOT / ".env")
key = get_api_key()
client = genai.Client(api_key=key)
for model in ["gemma-3-27b-it", "gemma-4-26b-a4b-it", "gemma-4-31b-it", "gemini-2.5-flash"]:
    t = time.monotonic()
    try:
        text = client.models.generate_content(model=model, contents="Say hi").text or ""
        print(f"{model:<22} OK    {time.monotonic() - t:4.1f}s  {text.strip()[:30]!r}")
    except Exception as exc:
        print(f"{model:<22} FAIL  {time.monotonic() - t:4.1f}s  {redact(str(exc), key)[:90]}")