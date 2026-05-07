# -*- coding: utf-8 -*-
import logging
import time
from pathlib import Path

from langchain.tools import tool

from my_tools.path_resolver import resolve_to_host_path

logger = logging.getLogger(__name__)

ALLOWED_DIRS = {"_task", "05-参考", "02-正文", "04-审稿", "03-状态"}

MAX_OUTPUT_CHARS = 50000


@tool("writer_reader", parse_docstring=True)
def writer_reader(
    description: str,
    path: str,
    start_line: int | None = None,
    end_line: int | None = None,
) -> str:
    """Writer 专用文件读取工具（受限白名单）。

    仅允许读取小说写作相关目录下的文件，包括：
    - _task/（写作任务汇总）
    - 02-正文/（正文章节）
    - 05-参考/（样式指纹）
    - 01-规划/chapters/（章节组细纲）
    - 04-审稿/（审计报告）
    - 03-状态/（状态卡、摘要、待办事项）

    禁止读取世界观、书籍元数据等其他目录。

    Args:
        description: 简要说明为什么读取此文件。务必先提供此参数。
        path: 要读取的文件绝对路径（支持沙箱路径如 /mnt/shared-data/...）
        start_line: 可选起始行号（1-indexed，包含）。与 end_line 配合使用可读取指定范围。
        end_line: 可选结束行号（1-indexed，包含）。与 start_line 配合使用可读取指定范围。
    """
    start_time = time.time()
    logger.info(
        "[writer_reader] >>> 调用开始 | description=%s | path=%s | lines=%s-%s",
        description, path, start_line or 1, end_line or "end",
    )

    host_path = resolve_to_host_path(path)
    logger.info("[writer_reader] 路径解析: %s -> %s", path, host_path)

    if not _is_allowed_path(host_path):
        elapsed = time.time() - start_time
        logger.warning(
            "[writer_reader] <<< 非白名单路径 | description=%s | path=%s | host_path=%s | 耗时=%.3fs",
            description, path, host_path, elapsed,
        )
        return (
            f"Error: 该文件不在允许读取的路径范围内。\n"
            f"writer_reader 仅允许读取以下目录：\n"
            f"- book/[小说名]/02-正文/第N-M章/_task/（写作任务汇总）\n"
            f"- book/[小说名]/02-正文/（正文章节，含上一章）\n"
            f"- book/[小说名]/05-参考/（样式指纹）\n"
            f"- book/[小说名]/01-规划/chapters/（章节组细纲）\n"
            f"- book/[小说名]/04-审稿/（审计报告）\n"
            f"- book/[小说名]/03-状态/（状态卡、摘要、待办事项）\n"
            f"请检查路径是否正确。"
        )

    try:
        target = Path(host_path)
        if not target.exists():
            elapsed = time.time() - start_time
            logger.warning(
                "[writer_reader] <<< 文件不存在 | description=%s | path=%s | host_path=%s | 耗时=%.3fs",
                description, path, host_path, elapsed,
            )
            return f"Error: File not found: {path}"
        if not target.is_file():
            elapsed = time.time() - start_time
            logger.warning(
                "[writer_reader] <<< 路径是目录 | description=%s | path=%s | host_path=%s | 耗时=%.3fs",
                description, path, host_path, elapsed,
            )
            return f"Error: Path is a directory, not a file: {path}"

        content = target.read_text(encoding="utf-8")

        if start_line is not None and end_line is not None:
            content = "\n".join(content.splitlines()[start_line - 1: end_line])
            logger.debug("[writer_reader] 读取行范围: %d-%d", start_line, end_line)

        elapsed = time.time() - start_time

        if not content:
            logger.info(
                "[writer_reader] <<< 文件为空 | description=%s | path=%s | 耗时=%.3fs",
                description, path, elapsed,
            )
            return "(empty)"

        content = _truncate_output(content, MAX_OUTPUT_CHARS)
        logger.info(
            "[writer_reader] <<< 读取成功 | description=%s | path=%s | host_path=%s | content_length=%d | 耗时=%.3fs",
            description, path, host_path, len(content), elapsed,
        )
        return content
    except PermissionError:
        elapsed = time.time() - start_time
        logger.error(
            "[writer_reader] <<< 权限拒绝 | description=%s | path=%s | host_path=%s | 耗时=%.3fs",
            description, path, host_path, elapsed,
        )
        return f"Error: Permission denied reading file: {path}"
    except UnicodeDecodeError as e:
        elapsed = time.time() - start_time
        logger.error(
            "[writer_reader] <<< 编码错误 | description=%s | path=%s | error=%s | 耗时=%.3fs",
            description, path, str(e), elapsed,
        )
        return f"Error: File encoding error: {str(e)}"
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(
            "[writer_reader] <<< 读取异常 | description=%s | path=%s | error=%s | 耗时=%.3fs",
            description, path, str(e), elapsed, exc_info=True,
        )
        return f"Error: Unexpected error reading file: {str(e)}"


def _is_allowed_path(file_path: str) -> bool:
    """检查文件路径是否在白名单中。"""
    parts = Path(file_path.replace("\\", "/")).parts
    if ALLOWED_DIRS & set(parts):
        return True
    if "01-规划" in parts and "chapters" in parts:
        return True
    return False


def _truncate_output(content: str, max_chars: int) -> str:
    """截断输出内容，避免 token 溢出。"""
    if len(content) <= max_chars:
        return content
    truncated = content[:max_chars]
    return f"{truncated}\n\n[内容已截断，超出 {max_chars} 字符限制]"
