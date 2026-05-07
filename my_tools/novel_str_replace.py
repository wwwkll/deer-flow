# -*- coding: utf-8 -*-
import logging
import time
from pathlib import Path

from langchain.tools import tool

from my_tools.path_resolver import resolve_to_host_path

logger = logging.getLogger(__name__)


ALLOWED_REPLACE_DIRS = {"_task", "05-参考", "02-正文", "04-审稿", "03-状态"}


def _is_allowed_path(file_path: str) -> bool:
    """检查文件路径是否在白名单中。

    允许操作的路径：
    1. _task/ 目录（写作任务汇总等）
    2. 05-参考/ 目录（样式指纹等）
    3. 02-正文/ 目录（正文章节）
    4. 01-规划/chapters/ 目录（章节组细纲）
    5. 04-审稿/ 目录（审计报告等）
    6. 03-状态/ 目录（状态卡、摘要、待办事项等）
    """
    parts = Path(file_path.replace("\\", "/")).parts
    if ALLOWED_REPLACE_DIRS & set(parts):
        return True
    if "01-规划" in parts and "chapters" in parts:
        return True
    return False


@tool("novel_str_replace", parse_docstring=True)
def novel_str_replace(
    file_path: str,
    old_str: str,
    new_str: str,
    replace_all: bool = False,
) -> str:
    """小说写手专用字符串替换工具（受限白名单）。

    仅允许操作以下目录下的文件：
    1. _task/ 目录（写作任务汇总等）
    2. 05-参考/ 目录（样式指纹等）
    3. 02-正文/ 目录（正文章节）
    4. 01-规划/chapters/ 目录（章节组细纲）
    5. 04-审稿/ 目录（审计报告等）

    Args:
        file_path: 要操作的文件绝对路径（支持沙箱路径如 /mnt/shared-data/... 或 host 路径）
        old_str: 要替换的原始字符串
        new_str: 替换后的新字符串
        replace_all: 是否替换所有匹配项，默认为 False 只替换第一个
    """
    start_time = time.time()
    logger.info(
        "[novel_str_replace] >>> 调用开始 | file_path=%s | old_str_length=%d | new_str_length=%d | replace_all=%s",
        file_path, len(old_str) if old_str else 0, len(new_str) if new_str else 0, replace_all,
    )
    logger.debug(
        "[novel_str_replace] 替换内容详情 | old_str=%s | new_str=%s",
        repr(old_str[:200]), repr(new_str[:200]),
    )

    host_path = resolve_to_host_path(file_path)
    logger.info("[novel_str_replace] 路径解析: %s -> %s", file_path, host_path)

    if not _is_allowed_path(host_path):
        elapsed = time.time() - start_time
        logger.warning(
            "[novel_str_replace] <<< 非规定目录 | file_path=%s | host_path=%s | 耗时=%.3fs",
            file_path, host_path, elapsed,
        )
        return (
            f"[提示] 这个文件不在你的操作范围内，按照规定你只能操作以下目录：\n"
            f"1. _task/（写作任务汇总）\n"
            f"2. 05-参考/（样式指纹）\n"
            f"3. 02-正文/（正文章节）\n"
            f"4. 01-规划/chapters/（章节组细纲）\n"
            f"5. 04-审稿/（审计报告）\n"
            f"6. 03-状态/（状态卡）\n"
            f"禁止操作其他目录！"
        )

    try:
        target = Path(host_path)
        if not target.exists():
            elapsed = time.time() - start_time
            logger.warning(
                "[novel_str_replace] <<< 文件不存在 | file_path=%s | host_path=%s | 耗时=%.3fs",
                file_path, host_path, elapsed,
            )
            return f"[FAIL] 文件不存在：{file_path}"
        if not target.is_file():
            elapsed = time.time() - start_time
            logger.warning(
                "[novel_str_replace] <<< 路径不是文件 | file_path=%s | host_path=%s | 耗时=%.3fs",
                file_path, host_path, elapsed,
            )
            return f"[FAIL] 路径不是文件：{file_path}"

        content = target.read_text(encoding="utf-8")
        logger.debug("[novel_str_replace] 文件读取成功 | content_length=%d", len(content))

        if old_str not in content:
            elapsed = time.time() - start_time
            logger.warning(
                "[novel_str_replace] <<< 未找到匹配字符串 | file_path=%s | old_str_length=%d | 耗时=%.3fs",
                file_path, len(old_str), elapsed,
            )
            return f"[FAIL] 未找到要替换的字符串：{file_path}"

        match_count = content.count(old_str)
        if replace_all:
            content = content.replace(old_str, new_str)
            logger.info("[novel_str_replace] 全量替换 | 匹配数=%d", match_count)
        else:
            content = content.replace(old_str, new_str, 1)
            logger.info("[novel_str_replace] 首次替换 | 总匹配数=%d（仅替换第1个）", match_count)

        target.write_text(content, encoding="utf-8")
        elapsed = time.time() - start_time
        logger.info(
            "[novel_str_replace] <<< 替换成功 | file_path=%s | host_path=%s | match_count=%d | replace_all=%s | 耗时=%.3fs",
            file_path, host_path, match_count, replace_all, elapsed,
        )
        return f"[OK] 字符串已替换：{file_path}"
    except PermissionError:
        elapsed = time.time() - start_time
        logger.error(
            "[novel_str_replace] <<< 权限拒绝(PermissionError) | file_path=%s | host_path=%s | 耗时=%.3fs",
            file_path, host_path, elapsed,
        )
        return f"[FAIL] 权限拒绝：{file_path}"
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(
            "[novel_str_replace] <<< 替换异常 | file_path=%s | host_path=%s | error=%s | 耗时=%.3fs",
            file_path, host_path, str(e), elapsed, exc_info=True,
        )
        return f"[FAIL] 替换失败：{str(e)}"
