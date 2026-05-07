"""Fix config.yaml by replacing invalid UTF-8 sequences with '?'."""
import shutil

config_path = r"c:\xiangmu\deer-flow\config.yaml"

with open(config_path, "rb") as f:
    raw = f.read()

# Decode with replacement, then save back as UTF-8
text = raw.decode("utf-8", errors="replace")

with open(config_path, "w", encoding="utf-8") as f:
    f.write(text)

# Verify
with open(config_path, "rb") as f:
    verify = f.read()
verify.decode("utf-8")  # Will raise if still invalid
print(f"Fixed! File size: {len(verify)} bytes, valid UTF-8")

# Count replacement chars
count = text.count("\ufffd")  # Unicode replacement character
print(f"Remaining replacement characters: {count}")
