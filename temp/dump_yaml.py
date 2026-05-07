"""Dump the raw YAML structure for novel-architect."""
import yaml

config_path = r"c:\xiangmu\deer-flow\config.yaml"

with open(config_path, "r", encoding="utf-8") as f:
    text = f.read()

# Parse YAML
config = yaml.safe_load(text)

# Check novel-architect
architect = config.get("subagents", {}).get("custom_agents", {}).get("novel-architect", {})
print(f"novel-architect keys: {list(architect.keys())}")
print(f"Has description: {'description' in architect}")
print(f"Has system_prompt: {'system_prompt' in architect}")

if 'description' in architect:
    desc = architect['description']
    print(f"\nDescription (first 200 chars): {desc[:200]}")
    print(f"\nDescription length: {len(desc)}")
