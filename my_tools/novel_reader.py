# -*- coding: utf-8 -*-
from langchain.tools import tool
from pathlib import Path

from my_tools.path_resolver import resolve_to_host_path


def _is_allowed_path(file_path: str) -> bool:
    """检查文件路径是否在白名单中。

    允许的路径：
    1. _task/ 目录下的文件（写作任务汇总等）
    2. 05-参考/ 目录下的文件（样式指纹等）
    3. 02-正文/ 目录下的文件（正文章节）
    """
    path_obj = Path(file_path.replace("\\", "/"))

    if "_task" in path_obj.parts:
        return True

    for part in path_obj.parts:
        if part == "05-参考":
            return True

    for part in path_obj.parts:
        if part == "02-正文":
            return True

    return False


@tool("novel_reader", parse_docstring=True)
def novel_reader(
    file_path: str,
) -> str:
    """小说写手专用读取工具（受限白名单）。

    仅允许读取以下目录下的文件：
    1. _task/ 目录（写作任务汇总等）
    2. 05-参考/ 目录（样式指纹等）
    3. 02-正文/ 目录（正文章节）

    Args:
        file_path: 要读取的文件绝对路径（支持沙箱路径如 /mnt/shared-data/...）
    """
    host_path = resolve_to_host_path(file_path)

    if not _is_allowed_path(host_path):
        return f"[FAIL] 权限拒绝：novel_reader 只允许读取 _task/、05-参考/、02-正文/ 目录下的文件，不允许读取：{file_path}"

    try:
        with open(host_path, "r", encoding="utf-8") as f:
            content = f.read()
        if not content:
            return f"[WARN] 文件为空：{file_path}"
        return content
    except FileNotFoundError:
        return f"[FAIL] 文件不存在：{file_path}"
    except PermissionError:
        return f"[FAIL] 权限拒绝：{file_path}"
    except Exception as e:
        return f"[FAIL] 读取失败：{str(e)}"
