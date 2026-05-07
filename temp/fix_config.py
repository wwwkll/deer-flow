"""Attempt to fix config.yaml by reading as GBK and saving as UTF-8."""
import shutil

backup_path = r"c:\xiangmu\deer-flow\config.yaml.bak"
config_path = r"c:\xiangmu\deer-flow\config.yaml"

# Backup first
shutil.copy2(config_path, backup_path)
print(f"Backup saved to {backup_path}")

# Try reading as GBK
with open(config_path, "rb") as f:
    raw = f.read()

# Method 1: Try GBK
try:
    text_gbk = raw.decode("gbk")
    print("Successfully decoded as GBK")
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(text_gbk)
    print("Converted GBK -> UTF-8 successfully")
    
    # Verify
    with open(config_path, "rb") as f:
        verify = f.read()
    verify.decode("utf-8")
    print("Verification: Valid UTF-8")
except UnicodeDecodeError as e:
    print(f"GBK decode failed: {e}")
    
    # Method 2: Replace invalid bytes and try utf-8
    print("Trying utf-8 with replacement...")
    text_utf8 = raw.decode("utf-8", errors="replace")
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(text_utf8)
    print("Saved with replacement characters")
