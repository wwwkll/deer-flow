"""Novel organize workflow - Steps 1-4 of chapter writing."""

import logging
from pathlib import Path
from typing import Any

from langgraph.graph import END, StateGraph

from deerflow.config.subagents_config import get_subagents_app_config
from deerflow.workflows.helpers import call_subagent, get_novel_base, normalize_chapter_group
from deerflow.workflows.registry import register_workflow
from deerflow.workflows.states import NovelWorkflowState
from my_tools.path_resolver import set_current_thread_id

logger = logging.getLogger(__name__)


def _is_parallel_enabled() -> bool:
    """Check if workflow parallel execution is enabled from config."""
    try:
        config = get_subagents_app_config()
        return config.workflow_parallel_enabled
    except Exception:
        return True


def confirm_chapter(state: NovelWorkflowState) -> dict[str, Any]:
    set_current_thread_id(state.get("thread_id"))

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
    model_name = state.get("model_name")

    logger.info(f"Organize workflow: organizing world reference for chapter {chapter_num}")

    novel_base = get_novel_base(thread_id=thread_id)
    if not novel_base:
        raise ValueError("无法获取小说根目录，请检查全局变量 novel_toc")
    output_path = f"{novel_base}/02-正文/{chapter_group}/_task/世界观参考.md"

    card_path = f"{novel_base}/card.json"
    state_path = f"{novel_base}/00-世界观/当前状态卡.md"
    outline_path = f"{novel_base}/01-规划/chapters/{chapter_group}-细纲.md"
    bible_path = f"{novel_base}/00-世界观/故事圣经.md"

    def _inject(label: str, path: str) -> str:
        # 提示词注入已禁用，让 Agent 自行读取文件
        rel_path = path.replace(novel_base + "/", "") if novel_base else path
        return f"## {label}\n路径：{path}（相对路径：{rel_path}）\n[请用read_file自行读取]\n"

    sections = _inject("小说名片", card_path)
    sections += _inject("当前状态", state_path)
    sections += _inject("章节细纲", outline_path)
    sections += _inject("故事圣经", bible_path)

    task = f"""你的任务是整理第{chapter_group}章组的世界观参考。

【重要提示】以下是需要参考的文件路径，请使用 read_file 工具自行读取：

{sections}

根据章节细纲中的剧情，提取相关的世界观设定，整理成参考文档。
将整理结果写入：{output_path}
"""

    try:
        result = await call_subagent("novel-world-organizer", task, parent_model=model_name)
        return {"world_reference": output_path}
    except Exception as e:
        logger.error(f"Organize world failed: {e}")
        return {"errors": [f"Organize world failed: {e}"]}


async def organize_characters(state: NovelWorkflowState) -> dict[str, Any]:
    novel_name = state.get("novel_name", "")
    chapter_num = state.get("chapter_num", 0)
    chapter_group = state.get("chapter_group", "")
    thread_id = state.get("thread_id")
    model_name = state.get("model_name")

    logger.info(f"Organize workflow: organizing character reference for chapter {chapter_num}")

    novel_base = get_novel_base(thread_id=thread_id)
    if not novel_base:
        raise ValueError("无法获取小说根目录，请检查全局变量 novel_toc")
    output_path = f"{novel_base}/02-正文/{chapter_group}/_task/人物参考.md"

    card_path = f"{novel_base}/card.json"
    state_path = f"{novel_base}/00-世界观/当前状态卡.md"
    outline_path = f"{novel_base}/01-规划/chapters/{chapter_group}-细纲.md"
    matrix_path = f"{novel_base}/00-世界观/角色矩阵.md"

    def _inject(label: str, path: str) -> str:
        # 提示词注入已禁用，让 Agent 自行读取文件
        rel_path = path.replace(novel_base + "/", "") if novel_base else path
        return f"## {label}\n路径：{path}（相对路径：{rel_path}）\n[请用read_file自行读取]\n"

    sections = _inject("小说名片", card_path)
    sections += _inject("当前状态", state_path)
    sections += _inject("章节细纲", outline_path)
    sections += _inject("角色矩阵", matrix_path)

    task = f"""你的任务是整理第{chapter_group}章组的人物参考。

【重要提示】以下是需要参考的文件路径，请使用 read_file 工具自行读取：

{sections}

根据章节细纲中的剧情，提取出场人物的详细信息，整理成参考文档。
将整理结果写入：{output_path}
"""

    try:
        result = await call_subagent("novel-character-organizer", task, parent_model=model_name)
        return {"character_reference": output_path}
    except Exception as e:
        logger.error(f"Organize characters failed: {e}")
        return {"errors": [f"Organize characters failed: {e}"]}


async def organize_items(state: NovelWorkflowState) -> dict[str, Any]:
    novel_name = state.get("novel_name", "")
    chapter_num = state.get("chapter_num", 0)
    chapter_group = state.get("chapter_group", "")
    thread_id = state.get("thread_id")
    model_name = state.get("model_name")

    logger.info(f"Organize workflow: organizing item reference for chapter {chapter_num}")

    novel_base = get_novel_base(thread_id=thread_id)
    if not novel_base:
        raise ValueError("无法获取小说根目录，请检查全局变量 novel_toc")
    output_path = f"{novel_base}/02-正文/{chapter_group}/_task/道具参考.md"

    card_path = f"{novel_base}/card.json"
    state_path = f"{novel_base}/00-世界观/当前状态卡.md"
    outline_path = f"{novel_base}/01-规划/chapters/{chapter_group}-细纲.md"
    bible_path = f"{novel_base}/00-世界观/故事圣经.md"

    def _inject(label: str, path: str) -> str:
        # 提示词注入已禁用，让 Agent 自行读取文件
        rel_path = path.replace(novel_base + "/", "") if novel_base else path
        return f"## {label}\n路径：{path}（相对路径：{rel_path}）\n[请用read_file自行读取]\n"

    sections = _inject("小说名片", card_path)
    sections += _inject("当前状态", state_path)
    sections += _inject("章节细纲", outline_path)
    sections += _inject("故事圣经", bible_path)

    task = f"""你的任务是整理第{chapter_group}章组的道具和技能参考。

【重要提示】以下是需要参考的文件路径，请使用 read_file 工具自行读取：

{sections}

整理当前章节出场的道具和技能，写入：{output_path}
"""

    try:
        result = await call_subagent("novel-item-organizer", task, parent_model=model_name)
        return {"item_reference": output_path}
    except Exception as e:
        logger.error(f"Organize items failed: {e}")
        return {"errors": [f"Organize items failed: {e}"]}


async def organize_storyline(state: NovelWorkflowState) -> dict[str, Any]:
    chapter_num = state.get("chapter_num", 0)
    chapter_group = state.get("chapter_group", "")
    thread_id = state.get("thread_id")
    model_name = state.get("model_name")

    logger.info(f"Organize workflow: organizing storyline reference for chapter {chapter_num}")

    novel_base = get_novel_base(thread_id=thread_id)
    if not novel_base:
        raise ValueError("无法获取小说根目录，请检查全局变量 novel_toc")
    output_path = f"{novel_base}/02-正文/{chapter_group}/_task/故事线参考.md"

    chapters_dir = f"{novel_base}/01-规划/chapters"
    outline_sections = []
    try:
        outline_files = sorted([f.name for f in Path(chapters_dir).glob("*-细纲.md")])
        for fname in outline_files:
            fpath = f"{chapters_dir}/{fname}"
            rel_path = fpath.replace(novel_base + "/", "") if novel_base else fpath
            outline_sections.append(f"## {fname}\n路径：{fpath}（相对路径：{rel_path}）\n[请用read_file自行读取]\n")
    except Exception as e:
        logger.warning(f"Failed to scan chapters dir: {e}")
        outline_sections = []

    outlines_content = "\n".join(outline_sections) if outline_sections else "未找到细纲文件，请用read_file自行读取。"

    card_path = f"{novel_base}/card.json"
    state_path = f"{novel_base}/00-世界观/当前状态卡.md"

    def _inject(label: str, path: str) -> str:
        # 提示词注入已禁用，让 Agent 自行读取文件
        rel_path = path.replace(novel_base + "/", "") if novel_base else path
        return f"## {label}\n路径：{path}（相对路径：{rel_path}）\n[请用read_file自行读取]\n"

    sections = _inject("小说名片", card_path)
    sections += _inject("当前状态", state_path)
    sections += outlines_content

    task = f"""你的任务是整理第{chapter_group}章组的故事线参考。

【重要提示】以下是需要参考的文件路径，请使用 read_file 工具自行读取：

{sections}

整理往期剧情线，写入：{output_path}
"""

    try:
        result = await call_subagent("novel-storyline-organizer", task, parent_model=model_name)
        return {"storyline_reference": output_path}
    except Exception as e:
        logger.error(f"Organize storyline failed: {e}")
        return {"errors": [f"Organize storyline failed: {e}"]}


async def assemble_context(state: NovelWorkflowState) -> dict[str, Any]:
    novel_name = state.get("novel_name", "")
    chapter_num = state.get("chapter_num", 0)
    chapter_group = state.get("chapter_group", "")
    thread_id = state.get("thread_id")

    logger.info(f"Organize workflow: assembling context for all chapter groups")

    novel_base = get_novel_base(thread_id=thread_id)
    if not novel_base:
        raise ValueError("无法获取小说根目录，请检查全局变量 novel_toc")

    # Find all chapter group directories under 02-正文/
    main_text_dir = Path(f"{novel_base}/02-正文")
    if not main_text_dir.exists():
        raise ValueError(f"正文目录不存在: {main_text_dir}")

    # Get all chapter group folders (directories starting with "第")
    chapter_groups = sorted([
        d.name for d in main_text_dir.iterdir()
        if d.is_dir() and d.name.startswith("第")
    ])

    if not chapter_groups:
        logger.warning(f"No chapter group folders found in {main_text_dir}")
        return {"writing_task_summary": ""}

    summaries = []

    for cg in chapter_groups:
        task_dir = main_text_dir / cg / "_task"
        if not task_dir.exists():
            logger.warning(f"Task directory not found: {task_dir}")
            continue

        # Remove old summary file if exists (before collecting md_files)
        summary_path = task_dir / "写作任务汇总.md"
        if summary_path.exists():
            try:
                summary_path.unlink()
                logger.info(f"Removed old summary: {summary_path}")
            except Exception as e:
                logger.warning(f"Failed to remove old summary {summary_path}: {e}")

        # Find all .md files in _task directory (after removing old summary)
        md_files = sorted(task_dir.glob("*.md"))
        if not md_files:
            logger.warning(f"No .md files found in {task_dir}")
            continue

        # Build sections from all .md files
        sections = []
        sections.append(f"# 写作任务汇总\n\n章节组：{cg}\n")

        for md_file in md_files:
            try:
                content = md_file.read_text(encoding="utf-8")
                sections.append(f"## {md_file.stem}\n\n{content}\n")
            except Exception as e:
                logger.warning(f"Failed to read {md_file}: {e}")

        # Write new summary
        output_path = task_dir / "写作任务汇总.md"
        output_path.write_text("\n".join(sections), encoding="utf-8")
        logger.info(f"Assembled writing task summary for {cg}: {output_path}")
        summaries.append(str(output_path))

    return {"writing_task_summary": "\n".join(summaries)}


def _create_parallel_workflow() -> StateGraph:
    """Create organize workflow with parallel execution for organize nodes."""
    from langgraph.constants import Send

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

    # Parallel organize nodes - all start after create_task_folder
    # Check if output files already exist, skip if they do
    def start_organize_parallel(state: NovelWorkflowState) -> list[Send] | str:
        chapter_group = state.get("chapter_group", "")
        thread_id = state.get("thread_id")
        novel_base = get_novel_base(thread_id=thread_id)
        
        if not novel_base:
            logger.warning("Cannot get novel_base, executing all organize nodes")
            return [
                Send("organize_world", state),
                Send("organize_characters", state),
                Send("organize_items", state),
                Send("organize_storyline", state),
            ]
        
        task_dir = Path(f"{novel_base}/02-正文/{chapter_group}/_task")
        
        # Define file mappings: (node_name, filename)
        organize_tasks = [
            ("organize_world", "世界观参考.md"),
            ("organize_characters", "人物参考.md"),
            ("organize_items", "道具参考.md"),
            ("organize_storyline", "故事线参考.md"),
        ]
        
        sends = []
        for node_name, filename in organize_tasks:
            file_path = task_dir / filename
            if file_path.exists():
                logger.info(f"Skipping {node_name}: {file_path} already exists")
            else:
                logger.info(f"Adding {node_name}: {file_path} not found")
                sends.append(Send(node_name, state))
        
        if not sends:
            logger.info("All organize files already exist, skipping to assemble_context")
            return "assemble_context"
        
        return sends

    workflow.add_conditional_edges("create_task_folder", start_organize_parallel)
    workflow.add_edge(["organize_world", "organize_characters", "organize_items", "organize_storyline"], "assemble_context")
    workflow.add_edge("assemble_context", END)

    return workflow.compile()


def _check_file_exists(state: NovelWorkflowState, filename: str) -> bool:
    """Check if a reference file already exists for the current chapter."""
    chapter_group = state.get("chapter_group", "")
    thread_id = state.get("thread_id")
    novel_base = get_novel_base(thread_id=thread_id)
    
    if not novel_base:
        return False
    
    file_path = Path(f"{novel_base}/02-正文/{chapter_group}/_task/{filename}")
    return file_path.exists()


def _create_sequential_workflow() -> StateGraph:
    """Create organize workflow with sequential execution."""
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
    
    # Sequential flow with file existence checks
    def route_after_task_folder(state: NovelWorkflowState) -> str:
        if _check_file_exists(state, "世界观参考.md"):
            logger.info("Skipping organize_world: 世界观参考.md already exists")
            return "organize_characters"
        return "organize_world"
    
    def route_after_world(state: NovelWorkflowState) -> str:
        if _check_file_exists(state, "人物参考.md"):
            logger.info("Skipping organize_characters: 人物参考.md already exists")
            return "organize_items"
        return "organize_characters"
    
    def route_after_characters(state: NovelWorkflowState) -> str:
        if _check_file_exists(state, "道具参考.md"):
            logger.info("Skipping organize_items: 道具参考.md already exists")
            return "organize_storyline"
        return "organize_items"
    
    def route_after_items(state: NovelWorkflowState) -> str:
        if _check_file_exists(state, "故事线参考.md"):
            logger.info("Skipping organize_storyline: 故事线参考.md already exists")
            return "assemble_context"
        return "organize_storyline"
    
    workflow.add_conditional_edges("create_task_folder", route_after_task_folder)
    workflow.add_conditional_edges("organize_world", route_after_world)
    workflow.add_conditional_edges("organize_characters", route_after_characters)
    workflow.add_conditional_edges("organize_items", route_after_items)
    workflow.add_edge("organize_storyline", "assemble_context")
    workflow.add_edge("assemble_context", END)

    return workflow.compile()


def create_organize_workflow() -> StateGraph:
    if _is_parallel_enabled():
        logger.info("Organize workflow: using parallel execution mode")
        return _create_parallel_workflow()
    else:
        logger.info("Organize workflow: using sequential execution mode")
        return _create_sequential_workflow()


register_workflow("organize", create_organize_workflow)
