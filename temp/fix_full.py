"""Fix config.yaml: read the backup, fix UTF-8 encoding, and rewrite as clean UTF-8."""
import shutil
import yaml

backup = r"c:\xiangmu\deer-flow\config.yaml.bak"
output = r"c:\xiangmu\deer-flow\config.yaml"

# Read raw bytes
with open(backup, "rb") as f:
    raw = f.read()

# Step 1: Decode with replacement to get a valid string
text = raw.decode("utf-8", errors="replace")

# Step 2: Parse as YAML to check structure
config = yaml.safe_load(text)

# Step 3: Check custom_agents
custom = config.get("subagents", {}).get("custom_agents", {})
print(f"Custom agents found: {len(custom)}")
for name, data in list(custom.items())[:3]:
    has_desc = "description" in data if isinstance(data, dict) else False
    has_prompt = "system_prompt" in data if isinstance(data, dict) else False
    print(f"  {name}: description={has_desc}, system_prompt={has_prompt}")
    if isinstance(data, dict):
        print(f"    Keys: {list(data.keys())}")

# Step 4: Check if description/system_prompt are being swallowed by UTF-8 damage
# Look for the raw text around "novel-architect"
import re

# Find "novel-architect:" in raw text
match = re.search(r'(\s+)novel-architect:\s*\n((?:.*\n)*?)\s+system_prompt:', text)
if match:
    print(f"\n\nFound novel-architect block with system_prompt!")
    print(f"Match: {match.group(0)[:300]}")
else:
    print("\n\nCould not find novel-architect with system_prompt in parsed text")
    # Try to find it in the raw bytes
    search = b"novel-architect:"
    pos = 0
    count = 0
    while True:
        pos = raw.find(search, pos)
        if pos == -1:
            break
        count += 1
        context = raw[pos:pos+200]
        print(f"\nOccurrence {count} at byte {pos}:")
        print(f"  {context!r}")
        pos += 1
