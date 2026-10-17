
from pathlib import Path
import shutil
import re

agent_file = Path("ai/country_agent.py")

if not agent_file.exists():
    raise SystemExit("ERROR: Run this script from your MUN project root.")

source = agent_file.read_text()

pattern = r'AURELIA_PROFILE\s*=\s*AgentProfile\((.*?)\n\)'
match = re.search(pattern, source, re.DOTALL)

if not match:
    raise SystemExit(
        "ERROR: Could not safely locate AURELIA_PROFILE. No files changed."
    )

# Use India as the default country for the existing single-agent endpoint.
# Keep the original personality and goals, adapting the country references.
profile = match.group(0)
updated = profile.replace('country_id="aurelia"', 'country_id="india"')
updated = updated.replace('name="Aurelia"', 'name="India"')
updated = updated.replace("Aurelia's", "India's")
updated = updated.replace("Aurelia itself", "India itself")

if updated == profile:
    raise SystemExit("ERROR: No profile changes detected. No files changed.")

backup = agent_file.with_suffix(".py.bak")
if not backup.exists():
    shutil.copy2(agent_file, backup)

agent_file.write_text(source[:match.start()] + updated + source[match.end():])

print("Updated the default AI profile to India.")
print(f"Backup: {backup}")
print("Next: restart the backend and test POST /ai/propose.")
