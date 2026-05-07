import logging
import re
import time

from langchain.tools import tool

logger = logging.getLogger(__name__)


@tool("ai_trace_detector")
def ai_trace_detector(file_path: str) -> str:
    """AI痕迹检测工具，检测正文中是否存在AI生成痕迹。

    Args:
        file_path: 正文文件路径

    Returns:
        检测报告
    """
    start_time = time.time()
    logger.info("[ai_trace_detector] >>> 调用开始 | file_path=%s", file_path)

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        logger.info("[ai_trace_detector] 文件读取成功 | file_path=%s | content_length=%d", file_path, len(content))
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(
            "[ai_trace_detector] <<< 文件读取失败 | file_path=%s | error=%s | 耗时=%.3fs",
            file_path, str(e), elapsed, exc_info=True,
        )
        return f"文件读取失败: {e}"

    issues = []
    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
    logger.info("[ai_trace_detector] 段落数=%d", len(paragraphs))

    if len(paragraphs) >= 5:
        lengths = [len(p) for p in paragraphs]
        avg_len = sum(lengths) / len(lengths)
        variance = sum((l - avg_len) ** 2 for l in lengths) / len(lengths)
        logger.debug("[ai_trace_detector] 段落等长检测 | avg_len=%.1f | variance=%.1f", avg_len, variance)
        if variance < 500:
            issues.append("警告：段落长度过于均匀，疑似AI生成")
            logger.warning("[ai_trace_detector] 段落长度过于均匀 | variance=%.1f < 500", variance)

    filler_words = ["似乎", "可能", "或许", "大概", "仿佛", "好像", "一定程度上"]
    filler_count = sum(content.count(w) for w in filler_words)
    logger.debug("[ai_trace_detector] 套话词检测 | filler_count=%d", filler_count)
    if filler_count > 5:
        issues.append(f"警告：套话词密度过高（发现{filler_count}个）")
        logger.warning("[ai_trace_detector] 套话词密度过高 | count=%d > 5", filler_count)

    transition_words = ["然而", "不过", "与此同时", "尽管如此", "总而言之", "综上所述"]
    transition_count = sum(content.count(w) for w in transition_words)
    logger.debug("[ai_trace_detector] 公式化转折检测 | transition_count=%d", transition_count)
    if transition_count > 3:
        issues.append(f"警告：公式化转折过多（发现{transition_count}个）")
        logger.warning("[ai_trace_detector] 公式化转折过多 | count=%d > 3", transition_count)

    ai_words = ["仿佛", "不禁", "宛如", "一丝", "抹去", "吞噬", "呢喃", "不由",
                "下意识", "微微", "陡然", "猛然", "骤然"]
    found_ai_words = [(w, content.count(w)) for w in ai_words if content.count(w) > 0]
    if found_ai_words:
        words_str = ", ".join(f"{w}({c})" for w, c in found_ai_words)
        issues.append(f"警告：发现AI痕迹词：{words_str}")
        logger.warning("[ai_trace_detector] 发现AI痕迹词 | %s", words_str)

    list_patterns = [
        r"(?:首先|其次|再次|最后|第一|第二|第三|第四|第五)[，、：]",
        r"(?:一是|二是|三是|四是|五是)[，、：]",
    ]
    for pattern in list_patterns:
        matches = re.findall(pattern, content)
        if len(matches) > 2:
            issues.append("警告：检测到列表式结构（首先/其次/最后等）")
            logger.warning("[ai_trace_detector] 检测到列表式结构 | pattern=%s | matches=%d", pattern, len(matches))
            break

    elapsed = time.time() - start_time
    if issues:
        logger.warning(
            "[ai_trace_detector] <<< 检测完成（发现问题） | file_path=%s | issues_count=%d | 耗时=%.3fs",
            file_path, len(issues), elapsed,
        )
        return "AI痕迹检测报告（发现问题）：\n" + "\n".join(f"- {issue}" for issue in issues)
    else:
        logger.info(
            "[ai_trace_detector] <<< 检测完成（无问题） | file_path=%s | 耗时=%.3fs",
            file_path, elapsed,
        )
        return "AI痕迹检测报告：未检测到明显AI痕迹。"
