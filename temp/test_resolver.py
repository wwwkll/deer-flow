import sys
sys.path.insert(0, "..")

with open("../temp/test_output.txt", "w", encoding="utf-8") as f:
    try:
        from my_tools.path_resolver import resolve_to_host_path

        test_paths = [
            "/mnt/shared-data/book/都市修仙聊天群",
            "/mnt/shared-data/book/测试小说/card.json",
            "/mnt/shared-data",
            "/some/other/path",
        ]

        for p in test_paths:
            resolved = resolve_to_host_path(p)
            f.write(f"{p}\n  -> {resolved}\n\n")

    except Exception as e:
        f.write(f"Error: {e}\n")
        import traceback
        traceback.print_exc(file=f)
