"""card_updater 工具：对 card.json 做"读 -> 改字段 -> 校验 -> 回写"原子更新。

设计动机：
- card_validator 只校验/修复格式问题，无法把 target_chapters 从 20 改成 35。
- master_writer 的写入白名单只放行 03-状态/ 目录，card.json 在小说根目录会被拒。
- 所以为 master 提供一个**专用**的 card 更新工具，避免它走 task→子 agent 兜底。

使用约定：
- 字符串字段传空串 ""  = 不更新该字段（保持原值）
- 数字字段传 -1         = 不更新该字段（保持原值）
- 其余值会替换原值，并按 card_validator 的规则二次校验
"""
from langchain.tools import tool
import json
import os
import time
import logging
from pathlib import Path

from my_tools.path_resolver import resolve_to_host_path

logger = logging.getLogger(__name__)


# 必填字段与允许值（与 card_validator 保持一致，单点定义在此处复制以避免循环依赖）
_STATUS_VALUES = ["planning", "writing", "completed", "paused"]
_REQUIRED_FIELDS = (
    "book_name",
    "genre",
    "concept",
    "platform",
    "status",
    "current_chapter",
    "target_chapters",
)


def _is_within_shared_data(file_path: str) -> bool:
    """检查路径是否在 shared-data 目录内（防止路径逃逸）。"""
    shared_data = resolve_to_host_path("/mnt/shared-data").replace("\\", "/")
    target = str(Path(file_path.replace("\\", "/")).resolve()).replace("\\", "/")
    return target.startswith(shared_data)


@tool("card_updater", parse_docstring=True)
def card_updater(
    description: str,
    card_path: str,
    book_name: str = "",
    genre: str = "",
    concept: str = "",
    platform: str = "",
    status: str = "",
    current_chapter: int = -1,
    target_chapters: int = -1,
) -> str:
    """更新 card.json 文件中的部分字段（不影响未指定的字段）。

    传值规则：字符串字段传空串 "" 表示不更新；数字字段传 -1 表示不更新。
    更新后会按 card.json 的规范进行二次校验（字段类型、status 取值、非负数等）。

    Args:
        description: 操作说明，简短描述为什么执行此次更新。ALWAYS PROVIDE THIS PARAMETER FIRST.
        card_path: card.json 文件路径（支持沙箱路径如 /mnt/shared-data/...）
        book_name: 新书名（""=不更新）
        genre: 新类型（""=不更新）
        concept: 新一句话概念（""=不更新）
        platform: 新平台（""=不更新）
        status: 新状态，取值 planning/writing/completed/paused（""=不更新）
        current_chapter: 新当前章节号（-1=不更新；必须 >= 0）
        target_chapters: 新目标章节数（-1=不更新；必须 >= 0）

    Returns:
        更新结果报告（包含改动列表、最终内容；失败则给出原因）
    """
    start_time = time.time()
    raw_input_path = card_path
    card_path = resolve_to_host_path(card_path).replace("\\", "/")
    logger.info("[card_updater] >>> input_path=%s | host_path=%s | desc=%s", raw_input_path, card_path, description)

    # 路径安全校验：仅在路径来自沙箱挂载点时校验，便于本地测试
    if "/mnt/" in raw_input_path.replace("\\", "/"):
        if not _is_within_shared_data(card_path):
            elapsed = time.time() - start_time
            logger.warning("[card_updater] <<< Path out of allowed range: %s | 耗时=%.3fs", card_path, elapsed)
            return f"[FAIL] 权限拒绝：路径超出允许范围：{raw_input_path}"

    # 必须为已存在的 card.json
    if not os.path.exists(card_path):
        elapsed = time.time() - start_time
        logger.warning("[card_updater] <<< 文件不存在 | card_path=%s | 耗时=%.3fs", card_path, elapsed)
        return (
            f"[FAIL] 文件不存在：{raw_input_path}\n"
            "提示：card_updater 不创建新文件，请先用 card_validator 的 auto_create 创建。"
        )

    # 读取并解析现有 card.json
    try:
        with open(card_path, "r", encoding="utf-8") as f:
            raw_content = f.read()
        card_data = json.loads(raw_content)
    except json.JSONDecodeError as e:
        elapsed = time.time() - start_time
        logger.error("[card_updater] <<< JSON 解析失败 | card_path=%s | error=%s | 耗时=%.3fs", card_path, str(e), elapsed)
        return (
            f"[FAIL] card.json 格式错误，无法解析：{str(e)}\n"
            "建议：先用 card_validator(fix=True) 修复格式后再执行更新。"
        )
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error("[card_updater] <<< 读取失败 | card_path=%s | error=%s | 耗时=%.3fs", card_path, str(e), elapsed, exc_info=True)
        return f"[FAIL] 读取文件失败：{str(e)}"

    if not isinstance(card_data, dict):
        elapsed = time.time() - start_time
        logger.error("[card_updater] <<< 顶层结构非对象 | card_path=%s | 耗时=%.3fs", card_path, elapsed)
        return "[FAIL] card.json 顶层结构必须是 JSON 对象"

    # 收集本次更新（仅对非默认值的入参生效）
    updates: dict = {}
    if book_name != "":
        updates["book_name"] = book_name
    if genre != "":
        updates["genre"] = genre
    if concept != "":
        updates["concept"] = concept
    if platform != "":
        updates["platform"] = platform
    if status != "":
        updates["status"] = status
    if current_chapter != -1:
        updates["current_chapter"] = current_chapter
    if target_chapters != -1:
        updates["target_chapters"] = target_chapters

    if not updates:
        elapsed = time.time() - start_time
        logger.info("[card_updater] <<< 无更新字段 | card_path=%s | 耗时=%.3fs", card_path, elapsed)
        return "[FAIL] 未提供任何更新字段。请至少指定一个非默认值的字段。"

    # 业务校验
    issues: list[str] = []
    if "status" in updates and updates["status"] not in _STATUS_VALUES:
        issues.append(f"status 值无效：{updates['status']}，应为 {_STATUS_VALUES} 之一")
    if "current_chapter" in updates and (not isinstance(updates["current_chapter"], int) or updates["current_chapter"] < 0):
        issues.append(f"current_chapter 必须为非负整数，实际：{updates['current_chapter']}")
    if "target_chapters" in updates and (not isinstance(updates["target_chapters"], int) or updates["target_chapters"] < 0):
        issues.append(f"target_chapters 必须为非负整数，实际：{updates['target_chapters']}")

    # 跨字段一致性：current 不应超过 target（若两者都已知）
    final_current = updates.get("current_chapter", card_data.get("current_chapter", 0))
    final_target = updates.get("target_chapters", card_data.get("target_chapters", 0))
    if isinstance(final_current, int) and isinstance(final_target, int) and final_target > 0 and final_current > final_target:
        issues.append(
            f"current_chapter ({final_current}) 不应超过 target_chapters ({final_target})；"
            "如需扩大目标章数，请同时更新 target_chapters。"
        )

    if issues:
        elapsed = time.time() - start_time
        logger.warning("[card_updater] <<< 校验失败 | card_path=%s | issues=%d | 耗时=%.3fs", card_path, len(issues), elapsed)
        return "[FAIL] 更新参数不合法：\n" + "\n".join(f"- {x}" for x in issues)

    # 记录变更（用于报告）
    change_log: list[str] = []
    for k, v in updates.items():
        old_v = card_data.get(k, "<未设置>")
        if old_v != v:
            change_log.append(f"{k}: {old_v} -> {v}")
        card_data[k] = v

    if not change_log:
        elapsed = time.time() - start_time
        logger.info("[card_updater] <<< 无实际变更 | card_path=%s | 耗时=%.3fs", card_path, elapsed)
        return (
            f"[OK] 无实际变更：传入字段值与原值相同。\n\n"
            f"路径：{raw_input_path}\n\n当前内容：\n{json.dumps(card_data, ensure_ascii=False, indent=2)}"
        )

    # 校验：更新后的 card 仍需包含全部 7 个必填字段
    missing = [f for f in _REQUIRED_FIELDS if f not in card_data]
    if missing:
        elapsed = time.time() - start_time
        logger.warning("[card_updater] <<< 必填字段缺失 | card_path=%s | missing=%s | 耗时=%.3fs", card_path, missing, elapsed)
        return (
            f"[FAIL] 更新后 card.json 仍缺少必填字段：{missing}\n"
            "建议：先用 card_validator(fix=True, auto_create=True, ...) 补齐字段。"
        )

    # 原子写回
    try:
        # 先写到临时文件再 rename，降低写入中断风险
        tmp_path = f"{card_path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(card_data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, card_path)
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error("[card_updater] <<< 写入失败 | card_path=%s | error=%s | 耗时=%.3fs", card_path, str(e), elapsed, exc_info=True)
        return f"[FAIL] 写入文件失败：{str(e)}"

    elapsed = time.time() - start_time
    logger.info("[card_updater] <<< 更新成功 | card_path=%s | changes=%d | 耗时=%.3fs", card_path, len(change_log), elapsed)
    return (
        f"[OK] card.json 已更新（{len(change_log)} 项变更）\n\n"
        f"路径：{raw_input_path}\n\n"
        f"变更：\n" + "\n".join(f"- {x}" for x in change_log) + "\n\n"
        f"最新内容：\n{json.dumps(card_data, ensure_ascii=False, indent=2)}"
    )
