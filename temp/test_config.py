"""Test that config.yaml can be loaded by the config-upgrade script."""
import yaml
import sys

config_path = r"c:\xiangmu\deer-flow\config.yaml"

try:
    with open(config_path, encoding='utf-8') as f:
        raw_text = f.read()
    print(f"File read successfully ({len(raw_text)} chars)")
    
    config = yaml.safe_load(raw_text)
    print(f"YAML parsed successfully")
    print(f"Config version: {config.get('config_version', 'N/A')}")
    print(f"Top-level keys: {list(config.keys())}")
    
    # Check for question marks in text
    q_count = raw_text.count('?')
    print(f"Question marks in file: {q_count}")
    
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
    sys.exit(1)
