"""Find all invalid UTF-8 bytes in config.yaml and their context."""
with open(r"c:\xiangmu\deer-flow\config.yaml", "rb") as f:
    content = f.read()

print(f"File size: {len(content)} bytes")
print()

# Find all invalid UTF-8 byte positions
errors = []
i = 0
while i < len(content):
    try:
        # Try to decode from position i
        content[i:i+4].decode('utf-8')
        i += 1
    except UnicodeDecodeError as e:
        err_start = i + e.start
        err_end = i + e.end
        # Show context
        ctx_start = max(0, err_start - 30)
        ctx_end = min(len(content), err_end + 30)
        context = content[ctx_start:ctx_end]
        
        # Try to decode the valid parts of context
        valid_before = content[ctx_start:err_start]
        valid_after = content[err_end:ctx_end]
        
        try:
            text_before = valid_before.decode('utf-8')
        except:
            text_before = repr(valid_before)
        try:
            text_after = valid_after.decode('utf-8')
        except:
            text_after = repr(valid_after)
        
        bad_bytes = content[err_start:err_end]
        
        print(f"Error at byte {err_start}:")
        print(f"  Bad bytes: {bad_bytes!r}")
        print(f"  Before: ...{text_before}")
        print(f"  After: {text_after}...")
        print()
        
        errors.append((err_start, err_end, bad_bytes))
        i = err_end  # Skip past the error

if not errors:
    print("No UTF-8 errors found!")
else:
    print(f"Found {len(errors)} encoding error(s)")
