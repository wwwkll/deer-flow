import logging
import os
import re
import time

from langchain.tools import tool

logger = logging.getLogger(__name__)


@tool("context_assembler")
def context_assembler(
    book_name: str,
    chapter_group: str,
    target_chapter: int,
    task_dir: str = "",
) -> str:
    """将各整理Agent的输出组装为写作任务汇总MD。

    Args:
        book_name: 小说名称
        chapter_group: 章节组范围，如"第01-05章"
        target_chapter: 当前要写的章节号
        task_dir: 任务目录路径（可选，默认使用标准路径）

    Returns:
        组装后的写作任务汇总文件路径
    """
    start_time = time.time()
    logger.info(
        "[context_assembler] >>> 调用开始 | book_name=%s | chapter_group=%s | target_chapter=%d | task_dir=%s",
        book_name, chapter_group, target_chapter, task_dir or "(自动计算)",
    )

    if not task_dir:
        task_dir = f"book/{book_name}/02-正文/{chapter_group}/_task"

    task_dir = task_dir.replace("\\", "/")
    book_path = f"book/{book_name}"

    logger.info("[context_assembler] 解析后路径 | task_dir=%s | book_path=%s", task_dir, book_path)

    def read_file(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
                logger.debug("[context_assembler] 读取文件成功 | path=%s | length=%d", path, len(content))
                return content
        except FileNotFoundError:
            logger.debug("[context_assembler] 文件不存在 | path=%s", path)
            return ""
        except Exception as e:
            logger.warning("[context_assembler] 读取文件失败 | path=%s | error=%s", path, str(e))
            return ""

    ref_files = {
        "世界观参考": f"{task_dir}/世界观参考.md",
        "人物参考": f"{task_dir}/人物参考.md",
        "道具参考": f"{task_dir}/道具参考.md",
        "故事线参考": f"{task_dir}/故事线参考.md",
        "用户要求": f"{task_dir}/用户要求.md",
    }

    for name, path in ref_files.items():
        logger.info("[context_assembler] 读取%s | path=%s", name, path)

    world_ref = read_file(ref_files["世界观参考"])
    char_ref = read_file(ref_files["人物参考"])
    item_ref = read_file(ref_files["道具参考"])
    story_ref = read_file(ref_files["故事线参考"])
    user_req = read_file(ref_files["用户要求"])

    outline_file = f"{book_path}/01-规划/chapters/{chapter_group}-细纲.md"
    logger.info("[context_assembler] 读取细纲 | path=%s", outline_file)
    outline_content = read_file(outline_file)

    rules_file = f"{book_path}/01-规划/本书规则.json"
    logger.info("[context_assembler] 读取规则 | path=%s", rules_file)
    rules = read_file(rules_file)

    state_file = f"{book_path}/03-状态/当前状态卡.md"
    logger.info("[context_assembler] 读取当前状态 | path=%s", state_file)
    current_state = read_file(state_file)

    hooks_file = f"{book_path}/03-状态/待办事项.md"
    logger.info("[context_assembler] 读取伏笔 | path=%s", hooks_file)
    hooks = read_file(hooks_file)

    summaries_file = f"{book_path}/03-状态/章节摘要汇总.md"
    logger.info("[context_assembler] 读取章节摘要 | path=%s", summaries_file)
    summaries = read_file(summaries_file)

    recent_summaries = ""
    if summaries:
        chapter_sections = re.findall(r"## 第\d+章 摘要.*?\n(?:[^#].*?\n)*", summaries, re.DOTALL)
        recent_summaries = "\n".join(chapter_sections[-3:])
        logger.info("[context_assembler] 提取最近3章摘要 | 摘要段落数=%d", len(chapter_sections[-3:]))

    output = f"""# 第{target_chapter}章 写作任务

## 当前章节
第{target_chapter}章（本组{chapter_group}）

## 用户要求
{user_req if user_req else "（无特殊要求，按细纲写作）"}

## 本组细纲（{chapter_group}）
{outline_content if outline_content else "（细纲未找到）"}

## 本书规则
{rules if rules else "（无特殊规则）"}

## 世界观参考
{world_ref if world_ref else "（无）"}

## 人物参考
{char_ref if char_ref else "（无）"}

## 道具参考
{item_ref if item_ref else "（无）"}

## 故事线参考
{story_ref if story_ref else "（无）"}

## 当前状态
{current_state if current_state else "（无）"}

## 伏笔提醒
{hooks if hooks else "（无）"}

## 前情提要
{recent_summaries if recent_summaries else "（无前情）"}
"""

    output_path = f"{task_dir}/写作任务汇总.md"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(output)

    elapsed = time.time() - start_time
    logger.info(
        "[context_assembler] <<< 组装完成 | output_path=%s | output_length=%d | 耗时=%.3fs",
        output_path, len(output), elapsed,
    )
    return output_path
