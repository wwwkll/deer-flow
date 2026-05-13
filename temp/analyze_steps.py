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
        
        # 分析 Run 7 (1085 checkpoints) 和 Run 8 (1739 checkpoints) 的详细 step 分布
        config = {"configurable": {"thread_id": thread_id}}
        
        # 收集所有 checkpoint 的 step 和 source
        step_source_map = {}
        all_meta = []
        async for cp_tuple in saver.alist(config, limit=10000):
            meta = cp_tuple.metadata
            if meta:
                run_id = meta.get("run_id", "unknown")
                step = meta.get("step", -1)
                source = meta.get("source", "unknown")
                agent = meta.get("agent_name", "unknown")
                model = meta.get("model_name", "unknown")
                all_meta.append({
                    "run_id": run_id,
                    "step": step,
                    "source": source,
                    "agent": agent,
                    "model": model,
                })
        
        # 分析两个大 run
        for target_run in ["019e21f1-2b49-7280-811d-0e6db1bd3e55", "019e2200-6096-7db3-92d3-974e6476fda2"]:
            run_metas = [m for m in all_meta if m["run_id"] == target_run]
            if not run_metas:
                continue
            
            print(f"\n{'='*60}")
            print(f"Run: {target_run[:8]}...")
            print(f"Total checkpoints: {len(run_metas)}")
            
            # Step 分布
            steps = sorted(set(m["step"] for m in run_metas))
            print(f"Step range: {min(steps)} ~ {max(steps)}")
            print(f"Unique steps: {len(steps)}")
            
            # 每个 step 有多少个 checkpoint
            step_counts = {}
            for m in run_metas:
                s = m["step"]
                step_counts[s] = step_counts.get(s, 0) + 1
            
            # 打印 step 分布（只打印有多个 checkpoint 的 step）
            multi_steps = {s: c for s, c in step_counts.items() if c > 1}
            if multi_steps:
                print(f"\nSteps with multiple checkpoints (showing top 20):")
                for s in sorted(multi_steps.keys())[:20]:
                    print(f"  step {s}: {multi_steps[s]} checkpoints")
            
            # source 分布
            sources = {}
            for m in run_metas:
                sources[m["source"]] = sources.get(m["source"], 0) + 1
            print(f"\nSource distribution: {sources}")
            
            # input checkpoints (用户消息)
            input_metas = [m for m in run_metas if m["source"] == "input"]
            print(f"\nUser input points: {len(input_metas)}")
            for m in input_metas[:5]:
                print(f"  step: {m['step']}")
        
        # 分析 Run 8 的详细流程
        print(f"\n\n{'='*60}")
        print(f"=== Run 8 详细流程分析 ===")
        run8_metas = [m for m in all_meta if m["run_id"] == "019e2200-6096-7db3-92d3-974e6476fda2"]
        
        # 按 step 排序
        run8_metas.sort(key=lambda x: x["step"])
        
        # 打印每个 step 的 checkpoint 数量
        step_groups = {}
        for m in run8_metas:
            s = m["step"]
            if s not in step_groups:
                step_groups[s] = {"count": 0, "sources": {}}
            step_groups[s]["count"] += 1
            src = m["source"]
            step_groups[s]["sources"][src] = step_groups[s]["sources"].get(src, 0) + 1
        
        print(f"\nStep-by-step checkpoint count:")
        for s in sorted(step_groups.keys()):
            info = step_groups[s]
            sources_str = ", ".join(f"{k}:{v}" for k, v in info["sources"].items())
            print(f"  step {s:4d}: {info['count']:3d} checkpoints ({sources_str})")

if __name__ == "__main__":
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main())
    loop.close()
