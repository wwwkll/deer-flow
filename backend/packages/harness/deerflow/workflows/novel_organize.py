"""Novel organize workflow - Steps 1-4 of chapter writing."""

import logging
from pathlib import Path
from typing import Any

from langgraph.graph import END, StateGraph

from deerflow.workflows.helpers import call_subagent, get_novel_base, normalize_chapter_group, read_file_safe
from deerflow.workflows.registry import register_workflow
from deerflow.workflows.states import NovelWorkflowState

logger = logging.getLogger(__name__)


def confirm_chapter(state: NovelWorkflowState) -> dict[str, Any]:
    novel_name = state.get("novel_name", "")
    chapter_num = state.get("chapter_num", 0)
    chapter_group = state.get("chapter_group", "")

    if not novel_name:
        raise ValueError("缺少必需参数: novel_name")
    if not chapter_num:
        raise ValueError("缺少必需参数: chapter_num")
    if not chapter_group:
        raise ValueError("缺少必需参数: chapter_group")

    chapter_group_normalized = normalize_chapter_group(chapter_group)

    logger.info(f"Organize workflow: confirm chapter {chapter_num} for {novel_name}")
    logger.info(f"Chapter group: {chapter_group_normalized}")

    return {"chapter_group": chapter_group_normalized}


def create_task_folder(state: NovelWorkflowState) -> dict[str, Any]:
    chapter_group = state.get("chapter_group", "")
    thread_id = state.get("thread_id")
    novel_base = get_novel_base(thread_id=thread_id)
    if not novel_base:
        raise ValueError("无法获取小说根目录，请检查全局变量 novel_toc")
    task_dir = Path(f"{novel_base}/02-正文/{chapter_group}/_task")
    task_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Created task folder: {task_dir}")
    return {}


async def organize_world(state: NovelWorkflowState) -> dict[str, Any]:
    novel_name = state.get("novel_name", "")
    chapter_num = state.get("chapter_num", 0)
    chapter_group = state.get("chapter_group", "")
    thread_id = state.get("thread_id")

    logger.info(f"Organize workflow: organizing world reference for chapter {chapter_num}")

    novel_base = get_novel_base(thread_id=thread_id)
    if not novel_base:
        raise ValueError("无法获取小说根目录，请检查全局变量 novel_toc")
    output_path = f"{novel_base}/02-正文/{chapter_group}/_task/世界观参考.md"

    card_path = f"{novel_base}/card.json"
    state_path = f"{novel_base}/03-状态/当前状态卡.md"
    outline_path = f"{novel_base}/01-规划/chapters/{chapter_group}-细纲.md"
    bible_path = f"{novel_base}/00-世界观/故事圣经.md"

    def _inject(label: str, path: str) -> str:
        content = read_file_safe(path)
        if content:
            return f"## {label}（已注入，不要再用read_file读取）\n\n{content}\n"
        return f"## {label}\n路径：{path}\n[未成功注入，请用read_file自行读取]\n"

    sections = _inject("小说名片", card_path)
    sections += _inject("当前状态", state_path)
    sections += _inject("章节细纲", outline_path)
    sections += _inject("故事圣经", bible_path)

    task = f"""你的任务是整理第{chapter_num}章的世界观参考。

以下参考内容已为你注入，标注"已注入"的不要用read_file重复读取，因为上下文有限。
标注"未成功注入"的，请用read_file按路径自行读取。

{sections}

整理当前章节需要的世界观设定，写入：{output_path}
"""

    try:
        result = await call_subagent("novel-world-organizer", task)
        return {"world_reference": output_path}
    except Exception as e:
        logger.error(f"Organize world failed: {e}")
        return {"errors": [f"Organize world failed: {e}"]}


async def organize_characters(state: NovelWorkflowState) -> dict[str, Any]:
    novel_name = state.get("novel_name", "")
    chapter_num = state.get("chapter_num", 0)
    chapter_group = state.get("chapter_group", "")
    thread_id = state.get("thread_id")

    logger.info(f"Organize workflow: organizing character reference for chapter {chapter_num}")

    novel_base = get_novel_base(thread_id=thread_id)
    if not novel_base:
        raise ValueError("无法获取小说根目录，请检查全局变量 novel_toc")
    output_path = f"{novel_base}/02-正文/{chapter_group}/_task/人物参考.md"

    card_path = f"{novel_base}/card.json"
    state_path = f"{novel_base}/03-状态/当前状态卡.md"
    outline_path = f"{novel_base}/01-规划/chapters/{chapter_group}-细纲.md"
    matrix_path = f"{novel_base}/00-世界观/角色矩阵.md"

    def _inject(label: str, path: str) -> str:
        content = read_file_safe(path)
        if content:
            return f"## {label}（已注入，不要再用read_file读取）\n\n{content}\n"
        return f"## {label}\n路径：{path}\n[未成功注入，请用read_file自行读取]\n"

    sections = _inject("小说名片", card_path)
    sections += _inject("当前状态", state_path)
    sections += _inject("章节细纲", outline_path)
    sections += _inject("角色矩阵", matrix_path)

    task = f"""你的任务是整理第{chapter_num}章的人物参考。

以下参考内容已为你注入，标注"已注入"的不要用read_file重复读取，因为上下文有限。
标注"未成功注入"的，请用read_file按路径自行读取。

{sections}

整理当前章节出场的人物信息，写入：{output_path}
"""

    try:
        result = await call_subagent("novel-character-organizer", task)
        return {"character_reference": output_path}
    except Exception as e:
        logger.error(f"Organize characters failed: {e}")
        return {"errors": [f"Organize characters failed: {e}"]}


async def organize_items(state: NovelWorkflowState) -> dict[str, Any]:
    novel_name = state.get("novel_name", "")
    chapter_num = state.get("chapter_num", 0)
    chapter_group = state.get("chapter_group", "")
    thread_id = state.get("thread_id")

    logger.info(f"Organize workflow: organizing item reference for chapter {chapter_num}")

    novel_base = get_novel_base(thread_id=thread_id)
    if not novel_base:
        raise ValueError("无法获取小说根目录，请检查全局变量 novel_toc")
    output_path = f"{novel_base}/02-正文/{chapter_group}/_task/道具参考.md"

    card_path = f"{novel_base}/card.json"
    state_path = f"{novel_base}/03-状态/当前状态卡.md"
    outline_path = f"{novel_base}/01-规划/chapters/{chapter_group}-细纲.md"
    bible_path = f"{novel_base}/00-世界观/故事圣经.md"

    def _inject(label: str, path: str) -> str:
        content = read_file_safe(path)
        if content:
            return f"## {label}（已注入，不要再用read_file读取）\n\n{content}\n"
        return f"## {label}\n路径：{path}\n[未成功注入，请用read_file自行读取]\n"

    sections = _inject("小说名片", card_path)
    sections += _inject("当前状态", state_path)
    sections += _inject("章节细纲", outline_path)
    sections += _inject("故事圣经", bible_path)

    task = f"""你的任务是整理第{chapter_num}章的道具和技能参考。

以下参考内容已为你注入，标注"已注入"的不要用read_file重复读取，因为上下文有限。
标注"未成功注入"的，请用read_file按路径自行读取。

{sections}

整理当前章节出场的道具和技能，写入：{output_path}
"""

    try:
        result = await call_subagent("novel-item-organizer", task)
        return {"item_reference": output_path}
    except Exception as e:
        logger.error(f"Organize items failed: {e}")
        return {"errors": [f"Organize items failed: {e}"]}


async def organize_storyline(state: NovelWorkflowState) -> dict[str, Any]:
    chapter_num = state.get("chapter_num", 0)
    chapter_group = state.get("chapter_group", "")
    thread_id = state.get("thread_id")

    logger.info(f"Organize workflow: organizing storyline reference for chapter {chapter_num}")

    novel_base = get_novel_base(thread_id=thread_id)
    if not novel_base:
        raise ValueError("无法获取小说根目录，请检查全局变量 novel_toc")
    output_path = f"{novel_base}/02-正文/{chapter_group}/_task/故事线参考.md"

    chapters_dir = f"{novel_base}/01-规划/chapters"
    try:
        outline_files = sorted([f.name for f in Path(chapters_dir).glob("*-细纲.md")])
        outline_sections = []
        for fname in outline_files:
            fpath = f"{chapters_dir}/{fname}"
            content = read_file_safe(fpath)
            if content:
                outline_sections.append(f"## {fname}（已注入，不要再用read_file读取）\n\n{content}\n")
            else:
                outline_sections.append(f"## {fname}\n路径：{fpath}\n[未成功注入，请用read_file自行读取]\n")
    except Exception as e:
        logger.warning(f"Failed to scan chapters dir: {e}")
        outline_sections = []

    outlines_content = "\n".join(outline_sections) if outline_sections else "未找到细纲文件，请用read_file自行读取。"

    card_path = f"{novel_base}/card.json"
    state_path = f"{novel_base}/03-状态/当前状态卡.md"

    def _inject(label: str, path: str) -> str:
        content = read_file_safe(path)
        if content:
            return f"## {label}（已注入，不要再用read_file读取）\n\n{content}\n"
        return f"## {label}\n路径：{path}\n[未成功注入，请用read_file自行读取]\n"

    sections = _inject("小说名片", card_path)
    sections += _inject("当前状态", state_path)
    sections += outlines_content

    task = f"""你的任务是整理第{chapter_num}章的故事线参考。

以下参考内容已为你注入，标注"已注入"的不要用read_file重复读取，因为上下文有限。
标注"未成功注入"的，请用read_file按路径自行读取。

{sections}

整理往期剧情线，写入：{output_path}
"""

    try:
        result = await call_subagent("novel-storyline-organizer", task)
        return {"storyline_reference": output_path}
    except Exception as e:
        logger.error(f"Organize storyline failed: {e}")
        return {"errors": [f"Organize storyline failed: {e}"]}


async def assemble_context(state: NovelWorkflowState) -> dict[str, Any]:
    novel_name = state.get("novel_name", "")
    chapter_num = state.get("chapter_num", 0)
    chapter_group = state.get("chapter_group", "")
    thread_id = state.get("thread_id")

    logger.info(f"Organize workflow: assembling context for chapter {chapter_num}")

    novel_base = get_novel_base(thread_id=thread_id)
    if not novel_base:
        raise ValueError("无法获取小说根目录，请检查全局变量 novel_toc")
    task_dir = f"{novel_base}/02-正文/{chapter_group}/_task"

    sections = []
    sections.append(f"# 写作任务汇总\n\n当前章节：第{chapter_num}章（本组：{chapter_group}）\n")

    ref_files = [
        ("细纲", f"{novel_base}/01-规划/chapters/{chapter_group}-细纲.md"),
        ("世界观参考", f"{task_dir}/世界观参考.md"),
        ("人物参考", f"{task_dir}/人物参考.md"),
        ("道具参考", f"{task_dir}/道具参考.md"),
        ("故事线参考", f"{task_dir}/故事线参考.md"),
        ("当前状态", f"{novel_base}/03-状态/当前状态卡.md"),
        ("伏笔池", f"{novel_base}/03-状态/待办事项.md"),
        ("章节摘要汇总", f"{novel_base}/03-状态/章节摘要汇总.md"),
    ]

    for label, path in ref_files:
        try:
            p = Path(path)
            if p.exists():
                content = p.read_text(encoding="utf-8")
                sections.append(f"## {label}\n\n{content}\n")
            else:
                logger.warning(f"Reference file not found: {path}")
        except Exception as e:
            logger.warning(f"Failed to read {path}: {e}")

    output_path = f"{task_dir}/写作任务汇总.md"
    Path(output_path).write_text("\n".join(sections), encoding="utf-8")
    logger.info(f"Assembled writing task summary: {output_path}")

    return {"writing_task_summary": output_path}


def create_organize_workflow() -> StateGraph:
    workflow = StateGraph(NovelWorkflowState)

    workflow.add_node("confirm_chapter", confirm_chapter)
    workflow.add_node("create_task_folder", create_task_folder)
    workflow.add_node("organize_world", organize_world)
    workflow.add_node("organize_characters", organize_characters)
    workflow.add_node("organize_items", organize_items)
    workflow.add_node("organize_storyline", organize_storyline)
    workflow.add_node("assemble_context", assemble_context)

    workflow.set_entry_point("confirm_chapter")
    workflow.add_edge("confirm_chapter", "create_task_folder")
    workflow.add_edge("create_task_folder", "organize_world")
    workflow.add_edge("organize_world", "organize_characters")
    workflow.add_edge("organize_characters", "organize_items")
    workflow.add_edge("organize_items", "organize_storyline")
    workflow.add_edge("organize_storyline", "assemble_context")
    workflow.add_edge("assemble_context", END)

    return workflow.compile()


register_workflow("organize", create_organize_workflow)
