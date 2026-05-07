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
    - 上级目录为 03-状态 的文件（写入操作）

    Args:
        file_path: 文件绝对路径（已解析为主机路径）

    Returns:
        是否允许写入
    """
    path_obj = Path(file_path.replace("\\", "/"))

    # 写入操作只允许 03-状态 目录
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


def _is_within_shared_data(file_path: str) -> bool:
    """检查路径是否在 shared-data 目录内（防止路径逃逸）。

    Args:
        file_path: 已解析的主机路径

    Returns:
        是否在 shared-data 目录内
    """
    shared_data = resolve_to_host_path("/mnt/shared-data").replace("\\", "/")
    target = str(Path(file_path.replace("\\", "/")).resolve()).replace("\\", "/")
    return target.startswith(shared_data)


@tool("master_writer", parse_docstring=True)
def master_writer(
    description: str,
    action: str,
    file_path: str,
    content: str = "",
    new_path: str = "",
) -> str:
    """小说主控专用写入工具（受限白名单）。

    仅允许以下操作：
    1. 创建目录（新建小说时，任意目录）
    2. 写入 03-状态 目录下的文件
    3. 移动小说项目目录下的任意文件或文件夹（可跨目录移动）
    4. 重命名小说项目目录下的任意文件或文件夹（同目录内重命名）

    Args:
        description: 操作说明，简短描述为什么执行此操作。ALWAYS PROVIDE THIS PARAMETER FIRST.
        action: 操作类型。create_dir=创建目录，write_file=写入文件，move_file=移动文件/文件夹，rename_file=重命名文件/文件夹
        file_path: 目标路径（绝对路径如 /mnt/shared-data/...，或相对路径如 book/小说名）
        content: 写入内容（仅 write_file 时使用）
        new_path: 新路径（仅 move_file 和 rename_file 时使用，表示文件/文件夹的新位置或新名称）
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
            elapsed = time.time() - start_time
            logger.info("[master_writer] create_dir success: %s (exists=%s) | 耗时=%.3fs", host_path, exists, elapsed)
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

        elif action == "move_file":
            if not new_path:
                return "[FAIL] 移动文件时必须提供 new_path 参数"
            host_new_path = _resolve_path(new_path)
            if not _is_within_shared_data(host_path):
                return f"[FAIL] 权限拒绝：源路径超出允许范围：{file_path}"
            if not _is_within_shared_data(host_new_path):
                return f"[FAIL] 权限拒绝：目标路径超出允许范围：{new_path}"
            if not os.path.exists(host_path):
                return f"[FAIL] 源文件/文件夹不存在：{file_path}"
            parent_dir = os.path.dirname(host_new_path)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)
            os.rename(host_path, host_new_path)
            logger.info("[master_writer] move_file success: %s -> %s", host_path, host_new_path)
            return f"[OK] 已移动：{file_path} -> {new_path}"

        elif action == "rename_file":
            if not new_path:
                return "[FAIL] 重命名文件时必须提供 new_path 参数"
            host_new_path = _resolve_path(new_path)
            if not _is_within_shared_data(host_path):
                return f"[FAIL] 权限拒绝：源路径超出允许范围：{file_path}"
            if not _is_within_shared_data(host_new_path):
                return f"[FAIL] 权限拒绝：目标路径超出允许范围：{new_path}"
            if not os.path.exists(host_path):
                return f"[FAIL] 源文件/文件夹不存在：{file_path}"
            parent_dir = os.path.dirname(host_new_path)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)
            os.rename(host_path, host_new_path)
            logger.info("[master_writer] rename_file success: %s -> %s", host_path, host_new_path)
            return f"[OK] 已重命名：{file_path} -> {new_path}"

        else:
            elapsed = time.time() - start_time
            logger.warning("[master_writer] <<< 不支持的操作类型 | action=%s | 耗时=%.3fs", action, elapsed)
            return f"[FAIL] 不支持的操作类型：{action}，仅支持 create_dir、write_file、move_file 或 rename_file"

    except PermissionError as e:
        elapsed = time.time() - start_time
        logger.error("[master_writer] <<< PermissionError: %s | 耗时=%.3fs", e, elapsed)
        return f"[FAIL] 权限拒绝：{file_path}"
    except OSError as e:
        elapsed = time.time() - start_time
        logger.error("[master_writer] <<< OSError: %s | 耗时=%.3fs", e, elapsed)
        return f"[FAIL] 文件操作失败：{str(e)}"
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error("[master_writer] <<< Exception: %s | 耗时=%.3fs", e, elapsed, exc_info=True)
        return f"[FAIL] 意外错误：{str(e)}"
