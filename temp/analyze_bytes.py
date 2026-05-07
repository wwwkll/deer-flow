"""Analyze the bytes around the corrupted characters in config.yaml."""
config_path = r"c:\xiangmu\deer-flow\config.yaml"

with open(config_path, "rb") as f:
    raw = f.read()

# Find positions of "保留关键数" 
search_text = "保留关键数".encode("utf-8")
positions = []
pos = 0
while True:
    pos = raw.find(search_text, pos)
    if pos == -1:
        break
    positions.append(pos)
    pos += 1

for p in positions:
    context = raw[p:p+30]
    print(f"\nPosition {p}: {context!r}")
    
    # Check the bytes after the search text
    after = raw[p+len(search_text):p+len(search_text)+10]
    print(f"  Bytes after: {after!r}")

# Also check what character the ? represents at position 30370
print("\n\nChecking the replacement characters:")
replacement = "?".encode("utf-8")  # 0x3F
count = raw.count(replacement)
print(f"ASCII '?' count: {count}")

# Show some context around ? characters
pos = 0
found = 0
while found < 5:
    pos = raw.find(replacement, pos)
    if pos == -1:
        break
    ctx = raw[pos-10:pos+10]
    print(f"  ? at {pos}: {ctx!r}")
    pos += 1
    found += 1
