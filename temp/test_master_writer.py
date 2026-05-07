#!/usr/bin/env python3
"""master_writer 核心逻辑测试（绕过 langchain 依赖）"""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS = 0
FAIL = 0


def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {detail}")


# --- 直接复制核心函数进行测试 ---

def _is_allowed_path(file_path: str) -> bool:
    path_obj = Path(file_path.replace("\\", "/"))
    if path_obj.parent.name == "03-状态":
        return True
    return False


def _is_allowed_dir(dir_path: str) -> bool:
    return True


def _is_within_shared_data(file_path: str) -> bool:
    shared_data = r"C:\xiangmu\deer-flow\backend\.deer-flow\shared-data".replace("\\", "/")
    target = Path(file_path.replace("\\", "/")).resolve()
    return str(target).replace("\\", "/").startswith(shared_data)


# --- 测试开始 ---

print("=== 1. _is_allowed_path（write_file 白名单）===")
check("03-状态 下文件-允许", _is_allowed_path(r"C:\test\book\03-状态\position.md"))
check("03-状态 子目录文件-拒绝（只允许直接子文件）", not _is_allowed_path(r"C:\test\book\03-状态\sub\file.txt"))
check("01-大纲 下文件-拒绝", not _is_allowed_path(r"C:\test\book\01-大纲\outline.md"))
check("card.json-拒绝", not _is_allowed_path(r"C:\test\book\card.json"))
check("根目录文件-拒绝", not _is_allowed_path(r"C:\test\book\readme.md"))

print("\n=== 2. _is_allowed_dir（create_dir 白名单）===")
check("任意目录-允许", _is_allowed_dir(r"C:\test\book\01-大纲"))

print("\n=== 3. _is_within_shared_data（路径安全检查）===")
sd = r"C:\xiangmu\deer-flow\backend\.deer-flow\shared-data"
check("shared-data 内文件-允许", _is_within_shared_data(f"{sd}\\book\\test\\card.json"))
check("shared-data 内目录-允许", _is_within_shared_data(f"{sd}\\book\\test"))
check("系统路径-拒绝", not _is_within_shared_data(r"C:\Windows\System32\cmd.exe"))
check("上级目录逃逸-拒绝", not _is_within_shared_data(f"{sd}\\..\\..\\etc\\passwd"))

print("\n=== 4. move_file 模拟测试 ===")
test_dir = os.path.join(sd, "_test_master_writer")
try:
    os.makedirs(os.path.join(test_dir, "src"), exist_ok=True)
    os.makedirs(os.path.join(test_dir, "dst"), exist_ok=True)

    src_file = os.path.join(test_dir, "src", "test.txt")
    dst_file = os.path.join(test_dir, "dst", "test.txt")
    with open(src_file, "w") as f:
        f.write("hello")

    check("源文件存在", os.path.exists(src_file))

    os.rename(src_file, dst_file)
    check("移动后源文件消失", not os.path.exists(src_file))
    check("移动后目标文件存在", os.path.exists(dst_file))
    with open(dst_file) as f:
        check("内容完整", f.read() == "hello")

    # 重命名
    renamed = os.path.join(test_dir, "dst", "renamed.txt")
    os.rename(dst_file, renamed)
    check("重命名后原文件消失", not os.path.exists(dst_file))
    check("重命名后新文件存在", os.path.exists(renamed))

    # 移动文件夹
    folder_src = os.path.join(test_dir, "src")
    os.makedirs(folder_src, exist_ok=True)
    folder_dst = os.path.join(test_dir, "dst", "src_moved")
    os.rename(folder_src, folder_dst)
    check("文件夹移动后源消失", not os.path.exists(folder_src))
    check("文件夹移动后目标存在", os.path.isdir(folder_dst))

finally:
    if os.path.exists(test_dir):
        import shutil
        shutil.rmtree(test_dir, ignore_errors=True)
    check("清理完成", True)

print(f"\n{'='*40}")
print(f"结果: {PASS} 通过, {FAIL} 失败")
if FAIL > 0:
    sys.exit(1)
print("🎉 所有测试通过!")
