import sys
import os
sys.path.insert(0, "..")

with open("../temp/test_output.txt", "w", encoding="utf-8") as f:
    try:
        from my_tools.master_writer import master_writer

        f.write("=== Final Test: master_writer path resolution ===\n\n")

        test_cases = [
            # 绝对路径
            ("/mnt/shared-data/book/最终测试", "abs_shared"),
            # 相对路径
            ("book/最终测试2", "rel_shared"),
            # 带 ./
            ("./book/最终测试3", "rel_dot"),
        ]

        for path, label in test_cases:
            result = master_writer.invoke({
                "description": f"test {label}",
                "action": "create_dir",
                "file_path": path,
            })
            f.write(f"[{label}] {path}\n  -> {result}\n\n")

        # Verify
        f.write("=== Verification ===\n")
        base = "E:/xiangmu/deer-flow-data/shared-data/book"
        for name in ["最终测试", "最终测试2", "最终测试3"]:
            path = f"{base}/{name}"
            exists = os.path.exists(path)
            f.write(f"  {name}: {'EXISTS' if exists else 'MISSING'}\n")

        # Cleanup
        import shutil
        for name in ["最终测试", "最终测试2", "最终测试3"]:
            path = f"{base}/{name}"
            if os.path.exists(path):
                shutil.rmtree(path)
        f.write("\nCleaned up\n")

    except Exception as e:
        f.write(f"Error: {e}\n")
        import traceback
        traceback.print_exc(file=f)
