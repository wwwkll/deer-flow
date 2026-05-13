import asyncio
import json
import sys
import selectors

sys.path.insert(0, r"c:\xiangmu\deer-flow\backend\packages\harness")

async def main():
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    
    conn_str = "postgresql://postgres:yuhan1014@localhost:5432/deerflow"
    thread_id = "4c95213d-13bd-44a5-b704-ef74d079a45b"
    
    # 主要分析 Run 8 (最新的大 run)
    target_run_id = "019e2200-6096-7db3-92d3-974e6476fda2"
    
    async with AsyncPostgresSaver.from_conn_string(conn_str) as saver:
        await saver.setup()
        
        config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
        checkpoint_tuple = await saver.aget_tuple(config)
        checkpoint = checkpoint_tuple.checkpoint
        channel_values = checkpoint.get("channel_values", {})
        messages = channel_values.get("messages", [])
        
        print(f"=== 最新完整消息列表 ({len(messages)} 条) ===\n")
        
        for i, msg in enumerate(messages):
            msg_type = type(msg).__name__
            
            if hasattr(msg, 'type'):
                actual_type = msg.type
            else:
                actual_type = msg_type
            
            if actual_type == 'human':
                content = msg.content if hasattr(msg, 'content') else ""
                if isinstance(content, str):
                    text = content
                elif isinstance(content, list):
                    text = " ".join([c.get('text', '') for c in content if isinstance(c, dict) and c.get('type') == 'text'])
                else:
                    text = str(content)
                print(f"\n{'='*60}")
                print(f"[{i}] USER: {text[:500]}")
                
            elif actual_type == 'ai':
                content = msg.content if hasattr(msg, 'content') else ""
                tool_calls = msg.tool_calls if hasattr(msg, 'tool_calls') else []
                
                text_preview = ""
                if isinstance(content, str) and content:
                    text_preview = content
                elif isinstance(content, list):
                    for c in content:
                        if isinstance(c, dict) and c.get('type') == 'text' and c.get('text'):
                            text_preview = c['text']
                            break
                
                if text_preview:
                    print(f"\n[{i}] AI TEXT: {text_preview[:500]}")
                
                if tool_calls:
                    for tc in tool_calls:
                        name = tc.get('name', '?') if isinstance(tc, dict) else getattr(tc, 'name', '?')
                        args = tc.get('args', {}) if isinstance(tc, dict) else getattr(tc, 'args', {})
                        
                        if name == 'workflow':
                            workflow_name = args.get('workflow_name', '?')
                            input_text = args.get('input', '')
                            print(f"\n[{i}] AI TOOL_CALL: workflow -> {workflow_name}")
                            print(f"  input: {input_text[:500]}")
                        elif name == 'read_file':
                            file_path = args.get('file_path', '?') if isinstance(args, dict) else str(args)
                            print(f"\n[{i}] AI TOOL_CALL: read_file -> {file_path[:200]}")
                        elif name == 'task':
                            task_desc = args.get('description', '?') if isinstance(args, dict) else str(args)[:200]
                            print(f"\n[{i}] AI TOOL_CALL: task -> {task_desc[:300]}")
                        elif name == 'glob':
                            pattern = args.get('pattern', '?') if isinstance(args, dict) else str(args)
                            print(f"\n[{i}] AI TOOL_CALL: glob -> {pattern}")
                        elif name == 'grep':
                            pattern = args.get('pattern', '?') if isinstance(args, dict) else str(args)
                            print(f"\n[{i}] AI TOOL_CALL: grep -> {pattern[:200]}")
                        else:
                            print(f"\n[{i}] AI TOOL_CALL: {name} -> {json.dumps(args, ensure_ascii=False, default=str)[:300]}")
                
            elif actual_type == 'tool':
                name = msg.name if hasattr(msg, 'name') else "?"
                content = msg.content if hasattr(msg, 'content') else ""
                if isinstance(content, str):
                    preview = content[:300]
                elif isinstance(content, list):
                    preview = str(content)[:300]
                else:
                    preview = str(content)[:300]
                print(f"  [{i}] TOOL_RESULT ({name}): {preview[:300]}")
            else:
                print(f"\n[{i}] {msg_type}: {str(msg)[:200]}")

if __name__ == "__main__":
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main())
    loop.close()
