import sys
import os
sys.path.insert(0, "..")

with open("../temp/test_output.txt", "w", encoding="utf-8") as f:
    try:
        from deerflow.config.agents_config import load_agent_config
        from deerflow.tools import get_available_tools

        config = load_agent_config("novel-master")
        tools = get_available_tools(
            groups=config.tool_groups,
            subagent_enabled=config.subagent_enabled,
            model_name="gpt-4o",
        )

        master_tool = None
        for t in tools:
            if t.name == "master_writer":
                master_tool = t
                break

        if master_tool is None:
            f.write("ERROR: master_writer tool NOT found in loaded tools!\n")
            f.write(f"Available tools: {[t.name for t in tools]}\n")
        else:
            f.write(f"master_writer tool found!\n")
            f.write(f"Tool name: {master_tool.name}\n")
            f.write(f"Tool type: {type(master_tool)}\n\n")

            test_base = "e:/xiangmu/deer-flow/temp/test_novel"
            dirs_to_create = [
                f"{test_base}/都市修仙聊天群",
                f"{test_base}/都市修仙聊天群/00-世界观",
                f"{test_base}/都市修仙聊天群/01-规划",
                f"{test_base}/都市修仙聊天群/01-规划/chapters",
                f"{test_base}/都市修仙聊天群/02-正文",
                f"{test_base}/都市修仙聊天群/03-状态",
                f"{test_base}/都市修仙聊天群/04-审稿",
                f"{test_base}/都市修仙聊天群/05-参考",
            ]

            for d in dirs_to_create:
                result = master_tool.invoke({
                    "description": "create novel directory",
                    "action": "create_dir",
                    "file_path": d,
                })
                f.write(f"  {d} -> {result}\n")

            f.write("\nVerifying directories exist:\n")
            for d in dirs_to_create:
                exists = os.path.exists(d)
                f.write(f"  {d} -> {'EXISTS' if exists else 'MISSING'}\n")

            import shutil
            if os.path.exists(test_base):
                shutil.rmtree(test_base)
                f.write(f"\nCleaned up: {test_base}\n")

    except Exception as e:
        f.write(f"Error: {e}\n")
        import traceback
        traceback.print_exc(file=f)
