import logging
import re
import time

from langchain.tools import tool

from my_tools.path_resolver import resolve_to_host_path

logger = logging.getLogger(__name__)


@tool("post_write_validator")
def post_write_validator(file_path: str) -> str:
    """后写验证工具，检查正文格式是否符合规范。

    Args:
        file_path: 正文文件路径（支持沙箱路径如 /mnt/shared-data/...）

    Returns:
        验证报告
    """
    start_time = time.time()
    logger.info("[post_write_validator] >>> 调用开始 | file_path=%s", file_path)

    # 解析沙箱路径到宿主机路径（与 writer_reader 行为一致）
    host_path = resolve_to_host_path(file_path)
    if str(host_path) != str(file_path):
        logger.info("[post_write_validator] 路径解析: %s -> %s", file_path, host_path)

    try:
        with open(host_path, "r", encoding="utf-8") as f:
            content = f.read()
        logger.info(
            "[post_write_validator] 文件读取成功 | file_path=%s | host_path=%s | content_length=%d",
            file_path, host_path, len(content),
        )
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(
            "[post_write_validator] <<< 文件读取失败 | file_path=%s | host_path=%s | error=%s | 耗时=%.3fs",
            file_path, host_path, str(e), elapsed, exc_info=True,
        )
        return f"文件读取失败: {e}"

    issues = []

    if re.search(r"^#{1,6}\s", content, re.MULTILINE):
        issues.append("错误：正文包含Markdown标题（#、##等）")
        logger.warning("[post_write_validator] 检测到Markdown标题")

    if re.search(r"^\s*[-*+]\s", content, re.MULTILINE):
        issues.append("错误：正文包含列表项（-、*、+）")
        logger.warning("[post_write_validator] 检测到列表项")

    if re.search(r"^\s*\d+\.\s", content, re.MULTILINE):
        issues.append("错误：正文包含编号列表（1.、2.等）")
        logger.warning("[post_write_validator] 检测到编号列表")

    if re.search(r"\*\*.*?\*\*", content):
        issues.append("错误：正文包含加粗标记（**）")
        logger.warning("[post_write_validator] 检测到加粗标记")

    if re.search(r"UPDATED_STATE|STATE_UPDATE|状态更新", content, re.IGNORECASE):
        issues.append("错误：正文包含状态更新标记")
        logger.warning("[post_write_validator] 检测到状态更新标记")

    # 英文引号检测：仅记录日志，不作为阻断项（LLM 生成正文难免混入直引号，
    # 过度修正会导致无限循环。如需统一引号格式，可手动或使用编辑器批量替换。）
    quote_count = content.count('"') + content.count("'")
    if quote_count > 0:
        logger.info("[post_write_validator] 检测到%d个英文引号（仅提示，非阻断）", quote_count)

    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", content))
    logger.debug("[post_write_validator] 中文字数统计 | chinese_chars=%d", chinese_chars)
    if chinese_chars < 1600:
        issues.append(f"警告：字数不足，当前{chinese_chars}字，要求1600字以上")
        logger.warning("[post_write_validator] 字数不足 | 当前=%d | 要求>=1600", chinese_chars)

    elapsed = time.time() - start_time
    if issues:
        logger.warning(
            "[post_write_validator] <<< 验证未通过 | file_path=%s | issues_count=%d | chinese_chars=%d | 耗时=%.3fs",
            file_path, len(issues), chinese_chars, elapsed,
        )
        return "验证未通过：\n" + "\n".join(f"- {issue}" for issue in issues)
    else:
        logger.info(
            "[post_write_validator] <<< 验证通过 | file_path=%s | chinese_chars=%d | 耗时=%.3fs",
            file_path, chinese_chars, elapsed,
        )
        return f"验证通过。字数：{chinese_chars}字。"
