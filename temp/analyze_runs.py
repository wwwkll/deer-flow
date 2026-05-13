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
        
        # 获取所有 checkpoint 历史
        checkpoints = []
        config = {"configurable": {"thread_id": thread_id}}
        async for cp_tuple in saver.alist(config, limit=10000):
            cp = cp_tuple.checkpoint
            meta = cp_tuple.metadata
            checkpoints.append({
                "id": cp.get("id", ""),
                "ts": cp.get("ts", ""),
                "metadata": meta,
            })
        
        print(f"总 checkpoints: {len(checkpoints)}")
        
        # 按 run_id 分组
        run_groups = {}
        for cp in checkpoints:
            meta = cp["metadata"]
            run_id = meta.get("run_id", "unknown") if meta else "unknown"
            if run_id not in run_groups:
                run_groups[run_id] = []
            run_groups[run_id].append(cp)
        
        print(f"\n=== 共 {len(run_groups)} 个 Run ===\n")
        
        for run_id, cps in run_groups.items():
            first_cp = cps[0]
            meta = first_cp["metadata"]
            
            print(f"\n{'='*60}")
            print(f"Run: {run_id}")
            print(f"  Checkpoints: {len(cps)}")
            print(f"  Agent: {meta.get('agent_name', 'N/A') if meta else 'N/A'}")
            print(f"  Model: {meta.get('model_name', 'N/A') if meta else 'N/A'}")
            print(f"  Graph: {meta.get('graph_id', 'N/A') if meta else 'N/A'}")
            print(f"  Tools: {meta.get('tools', 'N/A') if meta else 'N/A'}")
            print(f"  Novel TOC: {meta.get('novel_toc', 'N/A') if meta else 'N/A'}")
            
            # Step 分布
            steps = [cp["metadata"].get("step", -1) for cp in cps if cp["metadata"]]
            if steps:
                print(f"  Step range: {min(steps)} ~ {max(steps)}")
            
            # Source 分布
            sources = {}
            for cp in cps:
                src = cp["metadata"].get("source", "unknown") if cp["metadata"] else "unknown"
                sources[src] = sources.get(src, 0) + 1
            print(f"  Sources: {sources}")

if __name__ == "__main__":
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main())
    loop.close()
