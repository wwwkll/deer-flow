"""Fix truncated UTF-8 sequences in config.yaml backup and restore it."""
import shutil
import re

backup = r"c:\xiangmu\deer-flow\config.yaml.bak"
output = r"c:\xiangmu\deer-flow\config.yaml"

with open(backup, "rb") as f:
    raw = f.read()

# Strategy: Replace truncated UTF-8 sequences with replacement character,
# then carefully handle the YAML structure.
# The pattern \xe3\x80? means \xe3\x80 followed by ASCII '?' (0x3F)
# These should be complete 3-byte UTF-8 chars but the 3rd byte was replaced with '?'

# Common truncated patterns in this file:
# \xe3\x80? -> should be \xe3\x80\x82 (Chinese period 。) or \xe3\x80\x81 (、)
# The ? is at position where the 3rd byte should be

# Let's find all invalid UTF-8 sequences and fix them

def fix_truncated_utf8(data: bytes) -> bytes:
    """Fix truncated UTF-8 where the last byte(s) were replaced with ASCII '?'."""
    result = bytearray()
    i = 0
    while i < len(data):
        b = data[i]
        
        # Single-byte ASCII
        if b < 0x80:
            result.append(b)
            i += 1
            continue
        
        # Multi-byte UTF-8: determine expected length
        if (b >> 5) == 0b110:  # 2-byte: 110xxxxx
            expected = 2
        elif (b >> 4) == 0b1110:  # 3-byte: 1110xxxx
            expected = 3
        elif (b >> 3) == 0b11110:  # 4-byte: 11110xxx
            expected = 4
        else:
            # Invalid start byte - just copy as-is
            result.append(b)
            i += 1
            continue
        
        # Check if we have enough bytes
        remaining = data[i:i+expected]
        
        # Check if any byte in the sequence is ASCII '?' (0x3F) which indicates truncation
        if len(remaining) < expected:
            # Not enough bytes - replace with U+FFFD
            result.extend(b'\xef\xbf\xbd')
            i += len(remaining)
            continue
        
        # Check if the sequence is valid
        has_question_mark = (0x3F in remaining)
        
        if has_question_mark:
            # This sequence has been corrupted with '?' replacing a byte
            # Replace the whole sequence with replacement character
            result.extend(b'\xef\xbf\xbd')
            i += expected
            continue
        
        # Valid sequence - copy as-is
        result.extend(remaining)
        i += expected
    
    return bytes(result)

fixed = fix_truncated_utf8(raw)

# Verify
try:
    fixed.decode("utf-8")
    print("Fixed file is valid UTF-8!")
except UnicodeDecodeError as e:
    print(f"Still has UTF-8 errors: {e}")
    # Show remaining errors
    remaining = []
    i = 0
    while i < len(fixed):
        try:
            fixed[i:i+4].decode("utf-8")
            i += 1
        except UnicodeDecodeError as e2:
            remaining.append(i + e2.start)
            i += e2.end
    print(f"Remaining error positions: {remaining[:10]}...")

# Count ? chars
q_count = fixed.count(b'?')
print(f"ASCII '?' count in fixed: {q_count}")

# Write the fixed file
with open(output, "wb") as f:
    f.write(fixed)

print(f"\nFixed file written to {output}")
print(f"File size: {len(fixed)} bytes")

# Verify YAML can be parsed
import yaml
with open(output, "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

custom = config.get("subagents", {}).get("custom_agents", {})
print(f"Custom agents parsed: {len(custom)}")

for name in list(custom.keys())[:3]:
    data = custom[name]
    has_desc = "description" in data if isinstance(data, dict) else False
    has_prompt = "system_prompt" in data if isinstance(data, dict) else False
    print(f"  {name}: description={has_desc}, system_prompt={has_prompt}")
