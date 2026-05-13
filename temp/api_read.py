import requests
import json

thread_id = "4c95213d-13bd-44a5-b704-ef74d079a45b"
base_url = "http://localhost:8080"

# Get thread state
resp = requests.get(f"{base_url}/api/threads/{thread_id}/state")
if resp.status_code != 200:
    print(f"Error: {resp.status_code} {resp.text}")
else:
    data = resp.json()
    print("=== Thread State ===")
    print(json.dumps(list(data.keys()), indent=2))
    
    values = data.get("values", {})
    messages = values.get("messages", [])
    print(f"\nTotal messages: {len(messages)}")
    
    for i, msg in enumerate(messages):
        if isinstance(msg, dict):
            msg_type = msg.get("type", "?")
            content = msg.get("content", "")
            if isinstance(content, str):
                preview = content[:500]
            elif isinstance(content, list):
                texts = []
                for c in content:
                    if isinstance(c, dict):
                        if c.get("type") == "text":
                            texts.append(c.get("text", "")[:200])
                        elif c.get("type") == "tool_use":
                            texts.append(f"[tool:{c.get('name','')}]")
                        elif c.get("type") == "tool_result":
                            texts.append(f"[tool_result:{str(c.get('content',''))[:100]}]")
                preview = " | ".join(texts)[:500]
            else:
                preview = str(content)[:500]
            
            print(f"\n--- [{msg_type}] msg {i} ---")
            print(preview[:800])
