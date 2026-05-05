import sys
sys.path.insert(0, "..")

with open("../temp/test_output.txt", "w", encoding="utf-8") as f:
    try:
        from my_tools.path_resolver import _load_mounts, resolve_to_host_path

        mounts = _load_mounts()
        f.write(f"Loaded mounts: {mounts}\n\n")

        test_path = "/mnt/shared-data/book/测试小说"
        resolved = resolve_to_host_path(test_path)
        f.write(f"Input: {test_path}\n")
        f.write(f"Resolved: {resolved}\n")

    except Exception as e:
        f.write(f"Error: {e}\n")
        import traceback
        traceback.print_exc(file=f)
