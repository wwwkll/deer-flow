# -*- coding: utf-8 -*-
import logging
import time
from pathlib import Path

from langchain.tools import tool

from my_tools.path_resolver import resolve_to_host_path

logger = logging.getLogger(__name__)


ALLOWED_READ_DIRS = {"_task", "05-参考", "02-正文", "03-状态", "04-审稿"}


def _is_allowed_path(file_path: str) -> bool:
    """检查文件路径是否在白名单中。

    允许读取的路径：
    1. _task/ 目录（写作任务汇总等）
    2. 05-参考/ 目录（样式指纹等）
    3. 02-正文/ 目录（正文章节）
    4. 01-规划/chapters/ 目录（章节组细纲）
    5. 03-状态/ 目录（状态卡）
    """
    parts = Path(file_path.replace("\\", "/")).parts
    if ALLOWED_READ_DIRS & set(parts):
        return True
    if "01-规划" in parts and "chapters" in parts:
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
    4. 01-规划/chapters/ 目录（章节组细纲）
    5. 03-状态/ 目录（状态卡）

    Args:
        file_path: 要读取的文件绝对路径（支持沙箱路径如 /mnt/shared-data/...）
    """
    start_time = time.time()
    logger.info("[novel_reader] >>> 调用开始 | file_path=%s", file_path)

    host_path = resolve_to_host_path(file_path)
    logger.info("[novel_reader] 路径解析: %s -> %s", file_path, host_path)

    if not _is_allowed_path(host_path):
        elapsed = time.time() - start_time
        logger.warning(
            "[novel_reader] <<< 非规定文件 | file_path=%s | host_path=%s | 耗时=%.3fs",
            file_path, host_path, elapsed,
        )
        return (
            f"[提示] 这个文件不在你的读取范围内，按照规定你只能读取以下文件：\n"
            f"1. book/[小说名称]/02-正文/第N-M章/_task/写作任务汇总.md\n"
            f"2. book/[小说名称]/02-正文/第N-1章/第N-1章.md（上一章，最多回溯3章）\n"
            f"3. book/[小说名称]/05-参考/样式指纹.md\n"
            f"4. book/[小说名称]/01-规划/chapters/[章节组号]-细纲.md\n"
            f"5. book/[小说名称]/03-状态/当前状态卡.md\n"
            f"禁止读取其他未规定的文件！"
        )

    try:
        with open(host_path, "r", encoding="utf-8") as f:
            content = f.read()
        elapsed = time.time() - start_time
        if not content:
            logger.warning(
                "[novel_reader] <<< 文件为空 | file_path=%s | host_path=%s | 耗时=%.3fs",
                file_path, host_path, elapsed,
            )
            return f"[WARN] 文件为空：{file_path}"
        logger.info(
            "[novel_reader] <<< 读取成功 | file_path=%s | host_path=%s | content_length=%d | 耗时=%.3fs",
            file_path, host_path, len(content), elapsed,
        )
        return content
    except FileNotFoundError:
        elapsed = time.time() - start_time
        logger.warning(
            "[novel_reader] <<< 文件不存在 | file_path=%s | host_path=%s | 耗时=%.3fs",
            file_path, host_path, elapsed,
        )
        return f"[FAIL] 文件不存在：{file_path}"
    except PermissionError:
        elapsed = time.time() - start_time
        logger.error(
            "[novel_reader] <<< 权限拒绝(PermissionError) | file_path=%s | host_path=%s | 耗时=%.3fs",
            file_path, host_path, elapsed,
        )
        return f"[FAIL] 权限拒绝：{file_path}"
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(
            "[novel_reader] <<< 读取异常 | file_path=%s | host_path=%s | error=%s | 耗时=%.3fs",
            file_path, host_path, str(e), elapsed, exc_info=True,
        )
        return f"[FAIL] 读取失败：{str(e)}"
