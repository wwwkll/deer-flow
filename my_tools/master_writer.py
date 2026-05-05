from langchain.tools import tool
import os
import logging
from pathlib import Path

from my_tools.path_resolver import resolve_to_host_path

logger = logging.getLogger(__name__)


def _resolve_path(file_path: str) -> str:
    """解析路径：支持沙箱绝对路径、相对路径。

    1. 如果是绝对路径（以 / 开头），通过 resolve_to_host_path 转换
    2. 如果是相对路径，基于 /mnt/shared-data 拼接为绝对路径后再转换
       （小说项目统一存储在共享数据目录下）
    """
    normalized = file_path.replace("\\", "/").strip()
    if normalized.startswith("/"):
        return resolve_to_host_path(normalized)
    # 相对路径：去除 ./ 前缀，基于 /mnt/shared-data 挂载点拼接
    relative = normalized.removeprefix("./")
    return resolve_to_host_path(f"/mnt/shared-data/{relative}")


def _is_allowed_path(file_path: str) -> bool:
    """检查文件路径是否在白名单中。

    允许的路径：
    - 上级目录为 03-状态 的文件

    Args:
        file_path: 文件绝对路径（已解析为主机路径）

    Returns:
        是否允许写入
    """
    path_obj = Path(file_path.replace("\\", "/"))

    if path_obj.parent.name == "03-状态":
        return True

    return False


def _is_allowed_dir(dir_path: str) -> bool:
    """检查目录路径是否允许创建。

    允许在小说根目录下创建任何子目录。

    Args:
        dir_path: 目录绝对路径（已解析为主机路径）

    Returns:
        是否允许创建
    """
    return True


@tool("master_writer", parse_docstring=True)
def master_writer(
    description: str,
    action: str,
    file_path: str,
    content: str = "",
) -> str:
    """小说主控专用写入工具（受限白名单）。

    仅允许以下操作：
    1. 创建目录（新建小说时）
    2. 写入 03-状态 目录下的文件

    Args:
        description: 操作说明，简短描述为什么执行此操作。ALWAYS PROVIDE THIS PARAMETER FIRST.
        action: 操作类型。create_dir=创建目录，write_file=写入文件
        file_path: 目标路径（绝对路径如 /mnt/shared-data/...，或相对路径如 book/小说名）
        content: 写入内容（仅 write_file 时使用）
    """
    host_path = _resolve_path(file_path)
    logger.info("[master_writer] action=%s, input_path=%s, host_path=%s", action, file_path, host_path)

    try:
        if action == "create_dir":
            if not _is_allowed_dir(host_path):
                logger.warning("[master_writer] dir not allowed: %s", host_path)
                return f"[FAIL] 权限拒绝：不允许创建目录 {file_path}"
            os.makedirs(host_path, exist_ok=True)
            exists = os.path.exists(host_path)
            logger.info("[master_writer] create_dir success: %s (exists=%s)", host_path, exists)
            return f"[OK] 目录已创建：{file_path} (host: {host_path}, exists: {exists})"

        elif action == "write_file":
            if not content:
                return "[FAIL] 写入内容不能为空"
            if not _is_allowed_path(host_path):
                logger.warning("[master_writer] write not allowed: %s", host_path)
                return f"[FAIL] 权限拒绝：master_writer 只允许操作 03-状态 目录下的文件，不允许写入：{file_path}"
            parent_dir = os.path.dirname(host_path)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)
            with open(host_path, "w", encoding="utf-8") as f:
                f.write(content)
            logger.info("[master_writer] write_file success: %s", host_path)
            return f"[OK] 文件已写入：{file_path}"

        else:
            return f"[FAIL] 不支持的操作类型：{action}，仅支持 create_dir 或 write_file"

    except PermissionError as e:
        logger.error("[master_writer] PermissionError: %s", e)
        return f"[FAIL] 权限拒绝：{file_path}"
    except OSError as e:
        logger.error("[master_writer] OSError: %s", e)
        return f"[FAIL] 文件操作失败：{str(e)}"
    except Exception as e:
        logger.error("[master_writer] Exception: %s", e)
        return f"[FAIL] 意外错误：{str(e)}"
