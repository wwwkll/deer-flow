"""Extract the exact bytes of the novel-architect custom agent block."""

backup = r"c:\xiangmu\deer-flow\config.yaml.bak"

with open(backup, "rb") as f:
    raw = f.read()

# Find occurrence 2: the custom_agents novel-architect
search = b"novel-architect:\r\n      description:"
pos = raw.find(search)
if pos == -1:
    print("Not found!")
else:
    # Show next 500 bytes
    chunk = raw[pos:pos+500]
    print(f"Found at byte {pos}")
    print(f"Raw bytes (first 500):\n{chunk!r}")
    print()
    
    # Try to decode just this chunk
    try:
        decoded = chunk.decode("utf-8")
        print(f"Decoded OK:\n{decoded}")
    except UnicodeDecodeError as e:
        print(f"Decode error at {e.start}-{e.end}: {e}")
        print(f"Context: {chunk[max(0,e.start-20):e.end+20]!r}")
