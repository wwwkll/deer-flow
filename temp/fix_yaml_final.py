"""
Fix YAML structure: ensure system_prompt fields are properly separated
from description blocks by inserting correct line breaks.

The issue is that in the YAML, description blocks end like:
    ...text。
    system_prompt: |

But in the damaged file, they appear as:
    ...text。      system_prompt: |

We need to insert \r\n before '      system_prompt: |' when it's not
already on its own line.
"""
import re

config_path = r"c:\xiangmu\deer-flow\config.yaml"

with open(config_path, "rb") as f:
    raw = f.read()

# Decode as UTF-8 (already fixed)
text = raw.decode("utf-8")

# Pattern: some text (not starting with newline) followed by "      system_prompt: |"
# This means system_prompt is on the same "logical line" as the description content
# We need to split them

# The fix: find "      system_prompt:" and ensure there's a blank line before it
# In YAML literal blocks, content is indented 8 spaces. system_prompt is at 6 spaces.
# If we see non-blank text immediately before system_prompt at 6-space indent,
# we need to insert \r\n

count = 0
def fix_block_ending(m):
    global count
    count += 1
    return m.group(1) + '\r\n' + m.group(2)

# Match: end of description text + system_prompt on same visual "line"
# The pattern is: any non-newline char, then whitespace (including \r\n), then 6-space indent + system_prompt
# But the description block text is at 8-space indent, system_prompt at 6-space
# If there's no blank line between them, YAML treats system_prompt as part of description

# Look for: 8+ spaces of content, then \r\n, then "      system_prompt:"
# The key: if the content before \r\n is at 8+ space indent, and system_prompt is at 6,
# YAML should end the block. But if there are extra spaces or no proper \r\n, it fails.

# Actually the real issue: let me check the raw bytes more carefully
# Find all "system_prompt" positions
positions = [m.start() for m in re.finditer(r'system_prompt:', text)]
print(f"Found {len(positions)} system_prompt occurrences")

for pos in positions:
    # Show 100 chars before
    before = text[max(0, pos-100):pos]
    # Show what's immediately before system_prompt
    last_chars = before[-20:] if len(before) >= 20 else before
    print(f"\nAt {pos}: ...{last_chars!r}")
    
    # Check if there's a proper \r\n before it
    # Look for the pattern: \r\n + 6 spaces + system_prompt
    match = re.search(r'(\r?\n)(      system_prompt:)', text[pos-30:pos+20])
    if match:
        print(f"  Has proper line break: {match.group(1)!r}")
    else:
        print(f"  NO proper line break!")
