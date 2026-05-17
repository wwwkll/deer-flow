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
        
        for i, msg in enumerate(messages):
            if msg.get("type") != "ai":
                continue
                
            additional_kwargs = msg.get("additional_kwargs", {})
            content = msg.get("content", "")
            tool_calls = msg.get("tool_calls", [])
            
            content_type = type(content).__name__
            if isinstance(content, str):
                content_len = len(content)
                has_think_tag = "<tool_call>" in content
            elif isinstance(content, list):
                content_len = len(content)
                has_think_tag = any("<tool_call>" in str(part) for part in content)
            else:
                content_len = 0
                has_think_tag = False
            
            print(f"--- AI Message (index {i}) ---")
            print(f"  ID: {msg.get('id', 'N/A')}")
            print(f"  content type: {content_type}, length: {content_len}")
            print(f"  has_think_tag: {has_think_tag}")
            print(f"  tool_calls count: {len(tool_calls)}")
            print(f"  additional_kwargs keys: {list(additional_kwargs.keys())}")
            
            if isinstance(content, str) and content:
                print(f"  content first 300 chars: {content[:300]}")
            elif isinstance(content, list) and content:
                for j, part in enumerate(content[:3]):
                    print(f"  content[{j}]: {json.dumps(part, ensure_ascii=False)[:200]}")
            
            if isinstance(content, str) and has_think_tag:
                start = content.find("<tool_call>")
                print(f"  think tag at position {start}")
                print(f"  content around tag: {content[max(0,start-20):start+100]}")
            
            print()
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

asyncio.run(check_messages())
