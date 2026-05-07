"""
Fix YAML structure: insert proper line breaks before system_prompt fields.

Pattern to fix:
    ...调用此Agent。      system_prompt: |
Should become:
    ...调用此Agent。
      system_prompt: |
"""
import re
import yaml

config_path = r"c:\xiangmu\deer-flow\config.yaml"

with open(config_path, "r", encoding="utf-8") as f:
    text = f.read()

# Fix: replace "。      system_prompt:" with "。\r\n      system_prompt:"
# Also handle other Chinese punctuation that might precede system_prompt
pattern = r'([\u3002\uff0c\u3001\u3002])\s{6}(system_prompt:\s*\|)'
replacement = r'\1\r\n      \2'

fixed_text = re.sub(pattern, replacement, text)

# Count fixes
fixes = len(re.findall(pattern, text))
print(f"Fixed {fixes} system_prompt field boundaries")

# Write fixed file
with open(config_path, "w", encoding="utf-8") as f:
    f.write(fixed_text)

# Verify YAML parsing
with open(config_path, "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

custom = config.get("subagents", {}).get("custom_agents", {})
print(f"Custom agents parsed: {len(custom)}")

all_ok = True
for name in custom:
    data = custom[name]
    has_desc = "description" in data if isinstance(data, dict) else False
    has_prompt = "system_prompt" in data if isinstance(data, dict) else False
    status = "OK" if has_prompt else "MISSING"
    if not has_prompt:
        all_ok = False
    print(f"  {name}: description={'OK' if has_desc else 'MISSING'}, system_prompt={status}")

if all_ok:
    print("\nAll agents have system_prompt - YAML structure is correct!")
else:
    print("\nWARNING: Some agents still missing system_prompt!")
    # Debug: show one example
    example = custom.get("novel-architect", {})
    print(f"novel-architect keys: {list(example.keys())}")
    if "description" in example:
        desc = example["description"]
        print(f"description ends with: ...{desc[-80:]!r}")
