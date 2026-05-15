import yaml
import os

agents_dir = r"c:\xiangmu\deer-flow\backend\.deer-flow\agents"
for agent_name in ["outline-auditor", "outline-reviser", "outline-summarizer"]:
    config_path = os.path.join(agents_dir, agent_name, "config.yaml")
    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    print(f"{agent_name}:")
    print(f"  tools: {config.get('tools', [])}")
    print(f"  model: {config.get('model', 'N/A')}")
    print(f"  max_turns: {config.get('max_turns', 'N/A')}")
    print(f"  timeout_seconds: {config.get('timeout_seconds', 'N/A')}")
    print()
