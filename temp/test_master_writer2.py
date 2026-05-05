import sys
import os
sys.path.insert(0, "..")

with open("../temp/test_output.txt", "w", encoding="utf-8") as f:
    try:
        from my_tools.master_writer import master_writer

        f.write("Testing master_writer with various path formats...\n\n")

        test_cases = [
            # 绝对路径
            "/mnt/shared-data/book/相对路径测试",
            # 相对路径
            "book/相对路径测试2",
            # 带前导 ./ 的相对路径
            "./book/相对路径测试3",
        ]

        for path in test_cases:
            result = master_writer.invoke({
                "description": "test create dir",
                "action": "create_dir",
                "file_path": path,
            })
            f.write(f"Input: {path}\n  -> {result}\n\n")

        # Verify
        f.write("Verifying host paths:\n")
        for subdir in ["相对路径测试", "相对路径测试2", "相对路径测试3"]:
            path = f"E:/xiangmu/deer-flow-data/shared-data/book/{subdir}"
            exists = os.path.exists(path)
            f.write(f"  {path} -> {'EXISTS' if exists else 'MISSING'}\n")

        # Cleanup
        import shutil
        base = "E:/xiangmu/deer-flow-data/shared-data/book"
        for subdir in ["相对路径测试", "相对路径测试2", "相对路径测试3"]:
            path = f"{base}/{subdir}"
            if os.path.exists(path):
                shutil.rmtree(path)
        f.write("\nCleaned up test directories\n")

    except Exception as e:
        f.write(f"Error: {e}\n")
        import traceback
        traceback.print_exc(file=f)
