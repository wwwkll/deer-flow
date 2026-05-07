"""Check the original config structure from backup."""
import yaml

backup_path = r"c:\xiangmu\deer-flow\config.yaml.bak"

with open(backup_path, "rb") as f:
    raw = f.read()

# Try to decode as utf-8 first
try:
    text = raw.decode("utf-8")
    print("Backup is valid UTF-8")
except UnicodeDecodeError as e:
    print(f"Backup has UTF-8 error at {e.start}: {e}")
    # Try with replacement
    text = raw.decode("utf-8", errors="replace")

config = yaml.safe_load(text)
print(f"Config version: {config.get('config_version', 'N/A')}")
print(f"Top-level keys: {list(config.keys())}")

# Check subagents structure
subagents = config.get("subagents", {})
print(f"\nSubagent keys: {list(subagents.keys())}")

# Check builtins
builtins = subagents.get("builtins", {})
print(f"Builtins: {list(builtins.keys())}")

# Check custom_agents  
custom = subagents.get("custom_agents", {})
print(f"Custom agents count: {len(custom)}")

for name, data in list(custom.items())[:3]:
    has_system_prompt = "system_prompt" in data if isinstance(data, dict) else False
    print(f"  {name}: has system_prompt={has_system_prompt}, keys={list(data.keys()) if isinstance(data, dict) else 'N/A'}")
