"""card_updater 工具：对 card.json 做"读 -> 改字段 -> 校验 -> 回写"原子更新。

设计动机：
- card_validator 只校验/修复格式问题，无法把 target_chapters 从 20 改成 35。
- master_writer 的写入白名单只放行 03-状态/ 目录，card.json 在小说根目录会被拒。
- 所以为 master 提供一个**专用**的 card 更新工具，避免它走 task→子 agent 兜底。

使用约定：
- 字符串字段传空串 ""  = 不更新该字段（保持原值）
- 数字字段传 -1         = 不更新该字段（保持原值）
- 其余值会替换原值，并按 card_validator 的规则二次校验

新增（v2）：
- create_if_missing=True 时，允许补齐缺失的必填字段（未传入的用安全默认值），
  解决"card.json 缺 status 字段但 card_validator(fix=True) 又不补"的死循环场景。
- strict=True 时，写回时只保留 7 个标准字段，删除全部非标准字段（清理脏数据用）。
- current_chapter > target_chapters 不再 FAIL，改为在变更日志里给警告
  （常见场景：目标章数小于当前章数时，用户准备同时扩大 target_chapters）。
- 没有任何字段需要更新时返回 [OK] 而非 [FAIL]，避免 LLM 误判为错误。
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

# 补齐缺失必填字段时使用的安全默认值
_FIELD_DEFAULTS: dict = {
    "book_name": "",
    "genre": "",
    "concept": "",
    "platform": "",
    "status": "planning",
    "current_chapter": 0,
    "target_chapters": 0,
}


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
    create_if_missing: bool = False,
    strict: bool = True,
) -> str:
    """更新 card.json 文件中的部分字段（不影响未指定的字段）。

    card.json 严格 7 字段格式（不允许任何额外字段）：
      book_name / genre / concept / platform / status / current_chapter / target_chapters

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
        create_if_missing: 是否允许补齐缺失的必填字段（默认 False）。
            True 时：若现有 card 缺少必填字段，本次传入的字段直接写入，未传入的缺字段用
            安全默认值（status="planning"、章节字段=0、其他字符串字段=""）补齐。
            False 时（默认）：检测到任何必填字段缺失即拒绝写入，提示通过传 create_if_missing=True 修复。
        strict: 写回时是否只保留 7 个标准字段（默认 True，强制清理任何非标准字段）。
            True 时（默认）：写回前把不在 7 字段白名单内的键全部删掉，保证 card.json 始终干净。
            False 时：保留原有的非标准字段（仅在迁移/调试场景使用，不推荐）。

    Returns:
        更新结果报告（包含改动列表、最终内容；失败则给出原因）
    """
    start_time = time.time()
    raw_input_path = card_path
    card_path = resolve_to_host_path(card_path).replace("\\", "/")
    logger.info(
        "[card_updater] >>> input_path=%s | host_path=%s | desc=%s | create_if_missing=%s | strict=%s",
        raw_input_path, card_path, description, create_if_missing, strict,
    )

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

    # 没有更新字段：
    # - 若 strict=True 但 card_data 已经只含 7 个标准字段 → 没事干，直接 OK 不写盘
    # - 若 strict=True 且存在非标准字段 → 走下面的清理流程
    # - 若 strict=False → 没事干，直接 OK 不写盘
    has_extra_fields = any(k not in _REQUIRED_FIELDS for k in card_data.keys())
    if not updates and (not strict or not has_extra_fields):
        elapsed = time.time() - start_time
        logger.info("[card_updater] <<< 无更新字段 | card_path=%s | 耗时=%.3fs", card_path, elapsed)
        return (
            f"[OK] 未提供任何更新字段，card.json 保持原样。\n\n"
            f"路径：{raw_input_path}\n\n"
            f"当前内容：\n{json.dumps(card_data, ensure_ascii=False, indent=2)}\n\n"
            f"提示：若要修改字段，请显式传入；字符串字段传 \"\" 等于不传，数字字段传 -1 等于不传。"
        )

    # 业务校验
    issues: list[str] = []
    if "status" in updates and updates["status"] not in _STATUS_VALUES:
        issues.append(f"status 值无效：{updates['status']}，应为 {_STATUS_VALUES} 之一")
    if "current_chapter" in updates and (not isinstance(updates["current_chapter"], int) or updates["current_chapter"] < 0):
        issues.append(f"current_chapter 必须为非负整数，实际：{updates['current_chapter']}")
    if "target_chapters" in updates and (not isinstance(updates["target_chapters"], int) or updates["target_chapters"] < 0):
        issues.append(f"target_chapters 必须为非负整数，实际：{updates['target_chapters']}")

    if issues:
        elapsed = time.time() - start_time
        logger.warning("[card_updater] <<< 校验失败 | card_path=%s | issues=%d | 耗时=%.3fs", card_path, len(issues), elapsed)
        return "[FAIL] 更新参数不合法：\n" + "\n".join(f"- {x}" for x in issues)

    # 跨字段一致性：current 不应超过 target —— 改为警告而非拒绝
    # 常见场景：用户当前章已达原 target，正准备同时扩大 target_chapters。
    final_current = updates.get("current_chapter", card_data.get("current_chapter", 0))
    final_target = updates.get("target_chapters", card_data.get("target_chapters", 0))
    warnings: list[str] = []
    if isinstance(final_current, int) and isinstance(final_target, int) and final_target > 0 and final_current > final_target:
        warnings.append(
            f"current_chapter ({final_current}) > target_chapters ({final_target})，"
            "通常意味着 target_chapters 需要同时上调；本次仍按传入值写入。"
        )

    # 记录变更（用于报告）
    change_log: list[str] = []
    for k, v in updates.items():
        old_v = card_data.get(k, "<未设置>")
        if old_v != v:
            change_log.append(f"{k}: {old_v} -> {v}")
        card_data[k] = v

    # strict 模式：清理非标准字段（仅保留 7 个必填字段）
    removed_keys: list[str] = []
    if strict:
        for k in list(card_data.keys()):
            if k not in _REQUIRED_FIELDS:
                removed_keys.append(k)
                del card_data[k]
        if removed_keys:
            change_log.append(f"[strict] 清理非标准字段：{', '.join(removed_keys)}")

    # 必填字段缺失处理
    missing = [f for f in _REQUIRED_FIELDS if f not in card_data]
    if missing:
        if create_if_missing:
            # 补齐缺失字段用安全默认值
            filled: list[str] = []
            for f in missing:
                card_data[f] = _FIELD_DEFAULTS[f]
                filled.append(f"{f}={_FIELD_DEFAULTS[f]!r}")
            change_log.append(f"[create_if_missing] 补齐缺失必填字段：{', '.join(filled)}")
            logger.info("[card_updater] 补齐缺失字段 | card_path=%s | filled=%s", card_path, filled)
        else:
            elapsed = time.time() - start_time
            logger.warning(
                "[card_updater] <<< 必填字段缺失 | card_path=%s | missing=%s | 耗时=%.3fs",
                card_path, missing, elapsed,
            )
            return (
                f"[FAIL] 更新后 card.json 仍缺少必填字段：{missing}\n"
                "处理方式（任选其一）：\n"
                "  1. 本工具：重新调用并设 create_if_missing=True，未传入的缺字段会用安全默认值补齐；\n"
                "  2. card_validator：先用 fix=True 跑一遍（注意 fix=True 不会主动添加缺失字段，"
                "只补类型错误，所以缺字段场景下建议直接用本工具的 create_if_missing 模式）。"
            )

    # 没有任何实际变更（既无字段变化、也无 strict 清理）→ 返回 OK
    if not change_log:
        elapsed = time.time() - start_time
        logger.info("[card_updater] <<< 无实际变更 | card_path=%s | 耗时=%.3fs", card_path, elapsed)
        return (
            f"[OK] 无实际变更：传入字段值与原值相同。\n\n"
            f"路径：{raw_input_path}\n\n当前内容：\n{json.dumps(card_data, ensure_ascii=False, indent=2)}"
        )

    # 原子写回（先写 tmp 再 os.replace，降低写入中断风险）
    try:
        tmp_path = f"{card_path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(card_data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, card_path)
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error("[card_updater] <<< 写入失败 | card_path=%s | error=%s | 耗时=%.3fs", card_path, str(e), elapsed, exc_info=True)
        return f"[FAIL] 写入文件失败：{str(e)}"

    elapsed = time.time() - start_time
    logger.info("[card_updater] <<< 更新成功 | card_path=%s | changes=%d | removed=%d | warnings=%d | 耗时=%.3fs",
                card_path, len(change_log), len(removed_keys), len(warnings), elapsed)

    report_parts = [
        f"[OK] card.json 已更新（{len(change_log)} 项变更）",
        f"\n路径：{raw_input_path}",
        f"\n变更：\n" + "\n".join(f"- {x}" for x in change_log),
    ]
    if warnings:
        report_parts.append("\n警告：\n" + "\n".join(f"- ⚠️ {x}" for x in warnings))
    report_parts.append(f"\n最新内容：\n{json.dumps(card_data, ensure_ascii=False, indent=2)}")
    return "\n".join(report_parts)
