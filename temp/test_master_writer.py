import sys
import os
sys.path.insert(0, "..")

with open("../temp/test_output.txt", "w", encoding="utf-8") as f:
    try:
        from my_tools.master_writer import master_writer

        f.write("Testing master_writer with sandbox paths...\n\n")

        test_base = "/mnt/shared-data/book/都市修仙聊天群"
        dirs_to_create = [
            test_base,
            f"{test_base}/00-世界观",
            f"{test_base}/01-规划",
            f"{test_base}/01-规划/chapters",
            f"{test_base}/02-正文",
            f"{test_base}/03-状态",
            f"{test_base}/04-审稿",
            f"{test_base}/05-参考",
        ]

        for d in dirs_to_create:
            result = master_writer.invoke({
                "description": "create novel directory",
                "action": "create_dir",
                "file_path": d,
            })
            f.write(f"  {d}\n    -> {result}\n")

        # Verify host paths
        f.write("\nVerifying host paths exist:\n")
        host_base = "E:/xiangmu/deer-flow-data/shared-data/book/都市修仙聊天群"
        for subdir in ["", "00-世界观", "01-规划", "01-规划/chapters", "02-正文", "03-状态", "04-审稿", "05-参考"]:
            path = f"{host_base}/{subdir}" if subdir else host_base
            exists = os.path.exists(path)
            f.write(f"  {path}\n    -> {'EXISTS' if exists else 'MISSING'}\n")

        # Cleanup
        import shutil
        if os.path.exists(host_base):
            shutil.rmtree(host_base)
            f.write(f"\nCleaned up: {host_base}\n")

    except Exception as e:
        f.write(f"Error: {e}\n")
        import traceback
        traceback.print_exc(file=f)
