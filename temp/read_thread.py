import asyncio
import json
import sys
import selectors

sys.path.insert(0, r"c:\xiangmu\deer-flow\backend\packages\harness")

async def main():
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    
    conn_str = "postgresql://postgres:yuhan1014@localhost:5432/deerflow"
    thread_id = "4c95213d-13bd-44a5-b704-ef74d079a45b"
    
    async with AsyncPostgresSaver.from_conn_string(conn_str) as saver:
        await saver.setup()
        
        config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
        checkpoint_tuple = await saver.aget_tuple(config)
        
        if not checkpoint_tuple:
            print("No checkpoint found!")
            return
        
        checkpoint = checkpoint_tuple.checkpoint
        metadata = checkpoint_tuple.metadata
        
        print(f"=== 最新 Checkpoint ===")
        print(f"  checkpoint_id: {checkpoint.get('id')}")
        print(f"  metadata: {json.dumps(metadata, ensure_ascii=False, default=str)[:500]}")
        
        channel_values = checkpoint.get("channel_values", {})
        messages = channel_values.get("messages", [])
        
        print(f"\n=== 消息总数: {len(messages)} ===")
        
        type_counts = {}
        for msg in messages:
            t = type(msg).__name__
            type_counts[t] = type_counts.get(t, 0) + 1
        print(f"  消息类型统计: {type_counts}")
        
        print(f"\n--- 用户消息 ---")
        for i, msg in enumerate(messages):
            if hasattr(msg, 'type') and msg.type == 'human':
                content = msg.content if hasattr(msg, 'content') else str(msg)
                if isinstance(content, str):
                    print(f"\n[用户消息 {i}]")
                    print(f"  {content[:1000]}")
                elif isinstance(content, list):
                    texts = [c.get('text', '') for c in content if isinstance(c, dict) and c.get('type') == 'text']
                    print(f"\n[用户消息 {i}]")
                    print(f"  {' '.join(texts)[:1000]}")
        
        print(f"\n--- AI回复摘要 ---")
        ai_count = 0
        for i, msg in enumerate(messages):
            if hasattr(msg, 'type') and msg.type == 'ai':
                ai_count += 1
                content = msg.content if hasattr(msg, 'content') else ""
                tool_calls = msg.tool_calls if hasattr(msg, 'tool_calls') else []
                
                text_preview = ""
                if isinstance(content, str) and content:
                    text_preview = content[:500]
                elif isinstance(content, list):
                    for c in content:
                        if isinstance(c, dict):
                            if c.get('type') == 'text' and c.get('text'):
                                text_preview = c['text'][:500]
                                break
                
                tool_names = []
                if tool_calls:
                    for tc in tool_calls:
                        name = tc.get('name', '?') if isinstance(tc, dict) else getattr(tc, 'name', '?')
                        tool_names.append(name)
                
                if text_preview or tool_names:
                    print(f"\n[AI回复 {i}]")
                    if text_preview:
                        print(f"  text: {text_preview[:300]}")
                    if tool_names:
                        print(f"  tools: {', '.join(tool_names)}")
        
        # count checkpoints
        print(f"\n\n=== 统计 ===")
        count = 0
        async for _ in saver.alist({"configurable": {"thread_id": thread_id}}, limit=10000):
            count += 1
        print(f"  总 checkpoint 数: {count}")

if __name__ == "__main__":
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main())
    loop.close()
