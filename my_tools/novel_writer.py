# -*- coding: utf-8 -*-
import logging
import time
from pathlib import Path

from langchain.tools import tool

from my_tools.path_resolver import resolve_to_host_path

logger = logging.getLogger(__name__)


ALLOWED_WRITE_DIRS = {"_task", "05-参考", "02-正文", "04-审稿", "03-状态"}


def _is_allowed_path(file_path: str) -> bool:
    """检查文件路径是否在白名单中。

    允许写入的路径：
    1. _task/ 目录（写作任务汇总等）
    2. 05-参考/ 目录（样式指纹等）
    3. 02-正文/ 目录（正文章节）
    4. 01-规划/chapters/ 目录（章节组细纲）
    5. 04-审稿/ 目录（审计报告等）
    6. 03-状态/ 目录（状态卡、摘要、待办事项等）
    """
    parts = Path(file_path.replace("\\", "/")).parts
    if ALLOWED_WRITE_DIRS & set(parts):
        return True
    if "01-规划" in parts and "chapters" in parts:
        return True
    return False


@tool("novel_writer", parse_docstring=True)
def novel_writer(
    file_path: str,
    content: str,
) -> str:
    """小说写手专用写入工具（受限白名单）。

    仅允许写入以下目录下的文件：
    1. _task/ 目录（写作任务汇总等）
    2. 05-参考/ 目录（样式指纹等）
    3. 02-正文/ 目录（正文章节）
    4. 01-规划/chapters/ 目录（章节组细纲）
    5. 04-审稿/ 目录（审计报告等）

    Args:
        file_path: 要写入的文件绝对路径（支持沙箱路径如 /mnt/shared-data/... 或 host 路径）
        content: 要写入的文件内容
    """
    start_time = time.time()
    logger.info(
        "[novel_writer] >>> 调用开始 | file_path=%s | content_length=%d",
        file_path, len(content) if content else 0,
    )

    host_path = resolve_to_host_path(file_path)
    logger.info("[novel_writer] 路径解析: %s -> %s", file_path, host_path)

    if not _is_allowed_path(host_path):
        elapsed = time.time() - start_time
        logger.warning(
            "[novel_writer] <<< 非规定目录 | file_path=%s | host_path=%s | 耗时=%.3fs",
            file_path, host_path, elapsed,
        )
        return (
            f"[提示] 这个文件不在你的写入范围内，按照规定你只能写入以下目录：\n"
            f"1. _task/（写作任务汇总）\n"
            f"2. 05-参考/（样式指纹）\n"
            f"3. 02-正文/（正文章节）\n"
            f"4. 01-规划/chapters/（章节组细纲）\n"
            f"5. 04-审稿/（审计报告）\n"
            f"6. 03-状态/（状态卡）\n"
            f"禁止写入其他目录！"
        )

    try:
        target = Path(host_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        elapsed = time.time() - start_time
        logger.info(
            "[novel_writer] <<< 写入成功 | file_path=%s | host_path=%s | content_length=%d | 耗时=%.3fs",
            file_path, host_path, len(content), elapsed,
        )
        return f"[OK] 文件已写入：{file_path}"
    except PermissionError:
        elapsed = time.time() - start_time
        logger.error(
            "[novel_writer] <<< 权限拒绝(PermissionError) | file_path=%s | host_path=%s | 耗时=%.3fs",
            file_path, host_path, elapsed,
        )
        return f"[FAIL] 权限拒绝：{file_path}"
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(
            "[novel_writer] <<< 写入异常 | file_path=%s | host_path=%s | error=%s | 耗时=%.3fs",
            file_path, host_path, str(e), elapsed, exc_info=True,
        )
        return f"[FAIL] 写入失败：{str(e)}"
