"""master_writer 真实调用路径测试（覆盖 NameError(time) bug 修复）

之前 master_writer.py 漏 import time + 漏 start_time 初始化，导致：
- create_dir 成功分支（line 110-111）
- 不支持操作分支（line 163-165）
- 三个异常处理分支（line 167-178）
都会 NameError 崩溃。

现存的 test_master_writer.py 只测复制出来的辅助函数（绕开 langchain），
所以从未捕获过这个 bug。本文件直接 .invoke() 真实工具，覆盖所有出口。
"""

import sys
import os
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from my_tools.master_writer import master_writer


def test_create_dir_success():
    """create_dir 成功路径（修复前必崩 NameError）"""
    print("\n=== T1 create_dir 成功路径 ===")
    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, "newdir")
        result = master_writer.invoke({
            "description": "建临时目录",
            "action": "create_dir",
            "file_path": target,
        })
        assert isinstance(result, str), "返回值应是字符串而非异常"
        assert "[OK]" in result, f"应成功，实际：{result[:300]}"
        assert os.path.isdir(target), "目录应已创建"
        print(f"PASS  -> {result[:80]}")


def test_unsupported_action():
    """不支持的操作类型（修复前必崩 NameError）"""
    print("\n=== T2 不支持操作类型 ===")
    with tempfile.TemporaryDirectory() as tmp:
        result = master_writer.invoke({
            "description": "测试错误action",
            "action": "delete_everything",
            "file_path": tmp,
        })
        assert isinstance(result, str)
        assert "[FAIL]" in result and "不支持的操作类型" in result, result[:300]
        print(f"PASS  -> {result[:80]}")


def test_write_file_not_allowed():
    """写入非 03-状态 目录被拒（早返回，本路径无 time.time，但是 bug 触发场景之一）"""
    print("\n=== T3 write 非允许路径 ===")
    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, "foo.md")
        result = master_writer.invoke({
            "description": "试图写非 03-状态",
            "action": "write_file",
            "file_path": target,
            "content": "hi",
        })
        assert isinstance(result, str)
        assert "[FAIL]" in result and "只允许操作 03-状态" in result, result[:300]
        assert not os.path.exists(target)
        print(f"PASS  -> {result[:80]}")


def test_write_file_allowed_in_03_state():
    """写入 03-状态/ 目录放行"""
    print("\n=== T4 write 03-状态 放行 ===")
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = os.path.join(tmp, "03-状态")
        os.makedirs(state_dir)
        target = os.path.join(state_dir, "current-state.md")
        result = master_writer.invoke({
            "description": "写状态文件",
            "action": "write_file",
            "file_path": target,
            "content": "test content",
        })
        assert isinstance(result, str)
        assert "[OK]" in result, result[:300]
        with open(target, "r", encoding="utf-8") as f:
            assert f.read() == "test content"
        print(f"PASS  -> {result[:80]}")


def test_oserror_branch_no_namerror():
    """触发 OSError 异常处理分支：确保不再抛 NameError(time)

    Windows 下含非法字符 < > : | 等的路径会让 os.makedirs 抛 OSError。
    修复前会被 OSError 处理段的 `time.time() - start_time` 二次崩为 NameError，
    错误最终被 langchain 的 ToolNode 包装抛出而不是返回字符串。
    """
    print("\n=== T5 OSError 分支不再 NameError ===")
    if os.name != "nt":
        print("SKIP（非 Windows，跳过非法字符路径用例）")
        return
    bad_path = r"C:\xiangmu\deer-flow\backend\.deer-flow\shared-data\<bad>:dir"
    try:
        result = master_writer.invoke({
            "description": "触发OSError",
            "action": "create_dir",
            "file_path": bad_path,
        })
    except NameError as e:
        raise AssertionError(f"修复失效：仍抛 NameError: {e}") from e

    assert isinstance(result, str), f"应返回字符串，实际：{type(result)}"
    assert "[FAIL]" in result, f"非法路径应返回 FAIL：{result[:300]}"
    assert "NameError" not in result and "name 'time'" not in result.lower(), \
        f"返回里不应含 NameError 字样：{result[:300]}"
    print(f"PASS  -> {result[:120]}")


def main():
    tests = [
        test_create_dir_success,
        test_unsupported_action,
        test_write_file_not_allowed,
        test_write_file_allowed_in_03_state,
        test_oserror_branch_no_namerror,
    ]
    failed = []
    for t in tests:
        try:
            t()
        except Exception as e:
            import traceback
            traceback.print_exc()
            failed.append((t.__name__, str(e)))

    print("\n" + "=" * 60)
    if failed:
        print(f"[FAIL] {len(failed)}/{len(tests)} 测试失败：")
        for name, err in failed:
            print(f"  - {name}: {err}")
        sys.exit(1)
    else:
        print(f"[OK] 全部 {len(tests)} 项测试通过")


if __name__ == "__main__":
    main()
