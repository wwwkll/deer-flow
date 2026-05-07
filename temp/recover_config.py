"""
Recover config.yaml from backup by fixing truncated UTF-8 bytes.
Strategy: The backup file has patterns like \xe3\x80? where ? is ASCII 0x3F.
These are 3-byte UTF-8 chars where the 3rd byte got replaced with '?'.
We know the common chars:
  - 。 (U+3002) = \xe3\x80\x82  (Chinese period)
  - 、 (U+3001) = \xe3\x80\x81  (ideographic comma)
  - " (U+201C) = \xe2\x80\x9c  (left double quote)
  - " (U+201D) = \xe2\x80\x9d  (right double quote)
  - * (U+2018) = \xe2\x80\x98  (left single quote)
  - ' (U+2019) = \xe2\x80\x99  (right single quote)
  - — (U+2014) = \xe2\x80\x94  (em dash)
  - … (U+2026) = \xe2\x80\xa6  (ellipsis)
  - ： (U+FF1A) = \xef\xbc\x9a  (fullwidth colon)
  - ？ (U+FF1F) = \xef\xbc\x9f  (fullwidth question mark)
  - ！ (U+FF01) = \xef\xbc\x81  (fullwidth exclamation)
  - （ (U+FF08) = \xef\xbc\x88  (fullwidth left paren)
  - ） (U+FF09) = \xef\xbc\x89  (fullwidth right paren)
  - 【 (U+3010) = \xe3\x80\x90  (left black lenticular bracket)
  - 】 (U+3011) = \xe3\x80\x91  (right black lenticular bracket)

The pattern is: 2 valid UTF-8 bytes followed by ASCII '?' (0x3F) instead of the correct 3rd byte.
We need to analyze the context to guess the correct char.
"""
import re

backup = r"c:\xiangmu\deer-flow\config.yaml.bak"

with open(backup, "rb") as f:
    raw = f.read()

# Find all truncated UTF-8 sequences (2-byte prefix followed by '?')
# Pattern: valid 2-byte UTF-8 start + continuation byte + 0x3F
truncated_pattern = rb'([\xc0-\xff][\x80-\xbf])\x3f'

matches = list(re.finditer(truncated_pattern, raw))
print(f"Found {len(matches)} truncated UTF-8 sequences")

# Group by the 2-byte prefix to see which chars are affected
from collections import Counter
prefixes = Counter()
for m in matches:
    prefix = m.group(1)
    prefixes[prefix] += 1

print("\nPrefix frequency:")
for prefix, count in prefixes.most_common():
    print(f"  {prefix!r}: {count} occurrences")

# Now let's see the context around each unique prefix to determine the correct char
for prefix in prefixes:
    # Find first occurrence
    pos = raw.find(prefix + b'?')
    if pos == -1:
        continue
    # Show 40 bytes of context
    ctx_start = max(0, pos - 20)
    ctx_end = min(len(raw), pos + len(prefix) + 30)
    context = raw[ctx_start:ctx_end]
    
    # Try to decode the valid parts
    print(f"\n\nPrefix {prefix!r} at position {pos}:")
    # Replace the ? temporarily
    test = context.replace(prefix + b'?', prefix + b'\x00')
    try:
        decoded = test.replace(b'\x00', b'[?]').decode('utf-8')
        print(f"  Context: {decoded}")
    except:
        print(f"  Raw: {context!r}")
