import asyncio
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

async def check_messages():
    from langgraph_sdk import get_client
    
    client = get_client(url="http://localhost:2024")
    
    thread_id = "c61da651-97af-4bd5-a4e7-c093138e2a19"
    
    try:
        state = await client.threads.get_state(thread_id)
        messages = state.get("values", {}).get("messages", [])
        
        print(f"Total messages: {len(messages)}")
        print()
        
        ai_count = 0
        for i, msg in enumerate(messages):
            if msg.get("type") == "ai":
                ai_count += 1
                additional_kwargs = msg.get("additional_kwargs", {})
                has_reasoning = "reasoning_content" in additional_kwargs
                has_reasoning_field = "reasoning" in additional_kwargs
                content = msg.get("content", "")
                
                content_preview = ""
                if isinstance(content, str):
                    content_preview = content[:100]
                elif isinstance(content, list):
                    content_preview = str(content[0])[:100] if content else "[]"
                
                print(f"--- AI Message #{ai_count} (index {i}) ---")
                print(f"  ID: {msg.get('id', 'N/A')}")
                print(f"  Has reasoning_content: {has_reasoning}")
                print(f"  Has reasoning: {has_reasoning_field}")
                print(f"  additional_kwargs keys: {list(additional_kwargs.keys())}")
                if has_reasoning:
                    rc = additional_kwargs["reasoning_content"]
                    print(f"  reasoning_content preview: {str(rc)[:200]}")
                if has_reasoning_field:
                    r = additional_kwargs["reasoning"]
                    print(f"  reasoning preview: {str(r)[:200]}")
                print(f"  content preview: {content_preview}")
                
                if isinstance(content, str) and "<think>" in content:
                    print(f"  >>> Contains <think> tag in content!")
                print()
                
                if ai_count >= 5:
                    print("... (showing first 5 AI messages)")
                    break
        
        if ai_count == 0:
            print("No AI messages found in this thread!")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

asyncio.run(check_messages())
