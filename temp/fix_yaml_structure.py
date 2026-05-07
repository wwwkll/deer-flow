"""
Fix the YAML structure by properly terminating description blocks
before system_prompt fields.

The issue: damaged UTF-8 bytes in description blocks caused YAML parser
to swallow system_prompt as part of description.

We need to find patterns like:
    description: |
      ... damaged text ...
      system_prompt: |
And insert proper line breaks before system_prompt.
"""
import re

config_path = r"c:\xiangmu\deer-flow\config.yaml"

with open(config_path, "rb") as f:
    raw = f.read()

# First decode as UTF-8 (we already fixed encoding)
text = raw.decode("utf-8")

# The problem: in YAML, `description: |` creates a literal block.
# The block ends when indentation drops below the block's indentation level.
# But the damaged text may have lost proper line endings.
# 
# We need to find "      system_prompt:" and ensure it's on its own line
# with proper indentation, not embedded in description text.

# Pattern: find "      system_prompt:" that appears WITHOUT a preceding newline
# or appears after text that doesn't end with \r\n or \n at the proper indentation

# Strategy: Look for "system_prompt:" and check if it's properly terminated
# If the preceding non-whitespace chars are not at the start of a line with
# 6-space indentation, we need to insert proper breaks.

# Actually, the simpler approach: find all occurrences of text where
# "      system_prompt:" appears right after content without a blank line

# Let me first find the raw pattern
pattern = rb'[^\r\n]\s+system_prompt:'
matches = list(re.finditer(pattern, raw))
print(f"Found {len(matches)} potential system_prompt merges")

for m in matches[:5]:
    start = max(0, m.start() - 50)
    end = min(len(raw), m.end() + 30)
    context = raw[start:end]
    print(f"\nAt byte {m.start()}:")
    print(f"  {context!r}")

# Now let's fix: insert \r\n before each system_prompt that's improperly placed
fixed_text = text

# Pattern: content followed by system_prompt without proper YAML block termination
# We look for: ...text\n      system_prompt: |
# The text before should end the description block

# In YAML literal blocks, the block ends when a line has less indentation
# So we need: description text\n\n      system_prompt: |
# But currently: description text      system_prompt: |  (no newline)

# Find and fix: replace "text\n      system_prompt:" with "text\n\n      system_prompt:"
# But only when "text" is within a description block

count = 0
# Match: any non-empty line content followed by system_prompt at 6-space indent
pattern2 = r'([^\r\n])\n(      system_prompt:)'
def fix_match(m):
    global count
    count += 1
    return m.group(1) + '\n\n' + m.group(2)

fixed_text = re.sub(pattern2, fix_match, fixed_text)
print(f"\nFixed {count} system_prompt field boundaries")

# Also check for system_prompt that's directly concatenated without any newline
pattern3 = r'([^\r\n])      (system_prompt:)'
def fix_match3(m):
    global count
    count += 1
    return m.group(1) + '\n\n      ' + m.group(2)

fixed_text = re.sub(pattern3, fix_match3, fixed_text)
print(f"Fixed {count} total field boundaries")

# Write fixed text
with open(config_path, "w", encoding="utf-8") as f:
    f.write(fixed_text)

print(f"\nFixed file written")

# Verify YAML parsing
import yaml
with open(config_path, "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

custom = config.get("subagents", {}).get("custom_agents", {})
print(f"Custom agents parsed: {len(custom)}")

for name in list(custom.keys()):
    data = custom[name]
    has_desc = "description" in data if isinstance(data, dict) else False
    has_prompt = "system_prompt" in data if isinstance(data, dict) else False
    if not has_prompt:
        print(f"  MISSING system_prompt: {name}")
    else:
        print(f"  OK: {name}")
