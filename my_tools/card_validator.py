from langchain.tools import tool
import json
import os
import re
import logging
from pathlib import Path
from typing import Optional

from my_tools.path_resolver import resolve_to_host_path

logger = logging.getLogger(__name__)


def _is_within_shared_data(file_path: str) -> bool:
    """检查路径是否在 shared-data 目录内（防止路径逃逸）。

    Args:
        file_path: 已解析的主机路径

    Returns:
        是否在 shared-data 目录内
    """
    shared_data = resolve_to_host_path("/mnt/shared-data").replace("\\", "/")
    target = str(Path(file_path.replace("\\", "/")).resolve()).replace("\\", "/")
    return target.startswith(shared_data)


def _clean_json_content(content: str) -> str:
    """清理 JSON 内容中的注释和非标准内容。

    Args:
        content: 原始文件内容

    Returns:
        清理后的内容
    """
    lines = content.split('\n')
    cleaned_lines = []
    
    for line in lines:
        stripped = line.strip()
        
        # 跳过纯注释行
        if stripped.startswith('#') or stripped.startswith('//'):
            continue
        
        # 移除行内注释（# 后面的内容）
        # 需要小心处理：只在字符串外部移除注释
        cleaned_line = _remove_inline_comment(line)
        cleaned_lines.append(cleaned_line)
    
    return '\n'.join(cleaned_lines)


def _remove_inline_comment(line: str) -> str:
    """移除行内注释，但保留字符串内的 # 字符。

    Args:
        line: 原始行内容

    Returns:
        移除注释后的行
    """
    in_string = False
    string_char = None
    escape_next = False
    
    for i, char in enumerate(line):
        if escape_next:
            escape_next = False
            continue
        
        if char == '\\':
            escape_next = True
            continue
        
        if char in ('"', "'") and not in_string:
            in_string = True
            string_char = char
            continue
        
        if char == string_char and in_string:
            in_string = False
            string_char = None
            continue
        
        # 在字符串外遇到 # 或 //，删除后面的内容
        if not in_string and char == '#':
            # 检查是否是独立的 # （不是 JSON 值的一部分）
            # 简单处理：如果 # 前面是空白或开始，则认为是注释
            prefix = line[:i].rstrip()
            if not prefix or prefix.endswith(',') or prefix.endswith('{') or prefix.endswith('['):
                return line[:i].rstrip()
        
        if not in_string and char == '/' and i > 0 and line[i-1] == '/':
            return line[:i-1].rstrip()
    
    return line


@tool("card_validator")
def card_validator(
    card_path: str,
    fix: bool = True,
    auto_create: bool = False,
    book_name: str = "",
    genre: str = "",
    concept: str = "",
    platform: str = "",
) -> str:
    """验证并规范化 card.json 文件格式。

    Args:
        card_path: card.json 文件路径（支持沙箱路径如 /mnt/shared-data/...）
        fix: 是否自动修复格式问题（默认True）
        auto_create: 如果文件不存在是否自动创建（默认False）
        book_name: 自动创建时的书名
        genre: 自动创建时的类型
        concept: 自动创建时的一句话概念
        platform: 自动创建时的平台

    Returns:
        验证结果报告（包含是否通过、问题列表、修复后的内容）
    """
    card_path = resolve_to_host_path(card_path)
    card_path = card_path.replace("\\", "/")
    
    # 路径安全校验：防止路径逃逸（仅在生产环境校验）
    # 如果路径未被 resolve_to_host_path 转换（即不在沙箱挂载点内），跳过校验以支持测试
    original_path = card_path.replace("\\", "/")
    if "/mnt/" in card_path or original_path != card_path:
        # 路径已被解析，说明来自沙箱，需要校验
        if not _is_within_shared_data(card_path):
            elapsed = time.time() - start_time
            logger.warning("[card_validator] Path out of allowed range: %s | 耗时=%.3fs", card_path, elapsed)
            return f"[FAIL] 权限拒绝：路径超出允许范围：{card_path}"
    
    # 定义必填字段和类型
    REQUIRED_FIELDS = {
        "book_name": str,
        "genre": str,
        "concept": str,
        "platform": str,
        "status": str,
        "current_chapter": int,
        "target_chapters": int,
    }
    
    STATUS_VALUES = ["planning", "writing", "completed", "paused"]
    
    result = {
        "valid": True,
        "issues": [],
        "fixed": False,
        "content": None,
    }
    
    # 检查文件是否存在
    if not os.path.exists(card_path):
        if auto_create and book_name:
            try:
                card_data = {
                    "book_name": book_name,
                    "genre": genre or "未知",
                    "concept": concept or "",
                    "platform": platform or "",
                    "status": "planning",
                    "current_chapter": 0,
                    "target_chapters": 0,
                }
                os.makedirs(os.path.dirname(card_path), exist_ok=True)
                with open(card_path, "w", encoding="utf-8") as f:
                    json.dump(card_data, f, ensure_ascii=False, indent=2)
                result["fixed"] = True
                result["content"] = card_data
                logger.info("[card_validator] Created new card: %s", card_path)
                return f"[OK] card.json 已创建：{card_path}\n\n内容：\n{json.dumps(card_data, ensure_ascii=False, indent=2)}"
            except Exception as e:
                logger.error("[card_validator] Failed to create card: %s", e)
                return f"[FAIL] 创建文件失败：{str(e)}"
        else:
            return f"[FAIL] 文件不存在：{card_path}\n提示：设置 auto_create=True 和 book_name 参数可自动创建"
    
    # 读取文件
    try:
        with open(card_path, "r", encoding="utf-8") as f:
            raw_content = f.read()
        logger.info("[card_validator] 文件读取成功 | card_path=%s | raw_length=%d", card_path, len(raw_content))
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error("[card_validator] <<< 读取文件失败 | card_path=%s | error=%s | 耗时=%.3fs", card_path, str(e), elapsed, exc_info=True)
        return f"[FAIL] 读取文件失败：{str(e)}"
    
    # 尝试解析 JSON
    try:
        card_data = json.loads(raw_content)
    except json.JSONDecodeError as e:
        result["valid"] = False
        result["issues"].append(f"JSON 解析失败：{str(e)}")
        if fix:
            # 尝试修复：清理注释和非标准内容
            try:
                cleaned = _clean_json_content(raw_content)
                card_data = json.loads(cleaned)
                result["issues"].append("已自动修复：移除注释")
                result["fixed"] = True
            except Exception:
                elapsed = time.time() - start_time
                logger.error("[card_validator] <<< JSON修复失败 | card_path=%s | 耗时=%.3fs", card_path, elapsed)
                return f"[FAIL] JSON 格式错误，无法解析：{str(e)}\n建议：手动修复 JSON 格式"
        else:
            elapsed = time.time() - start_time
            logger.error("[card_validator] <<< JSON格式错误(未启用修复) | card_path=%s | 耗时=%.3fs", card_path, elapsed)
            return f"[FAIL] JSON 格式错误：{str(e)}"
    
    # 验证字段
    for field, field_type in REQUIRED_FIELDS.items():
        if field not in card_data:
            result["valid"] = False
            result["issues"].append(f"缺少必填字段：{field}")
        elif not isinstance(card_data[field], field_type):
            result["valid"] = False
            result["issues"].append(
                f"字段类型错误：{field} 应为 {field_type.__name__}，实际为 {type(card_data[field]).__name__}"
            )
            if fix:
                try:
                    if field_type == int:
                        card_data[field] = int(card_data[field])
                        result["fixed"] = True
                    elif field_type == str:
                        card_data[field] = str(card_data[field])
                        result["fixed"] = True
                except Exception:
                    result["issues"].append(f"无法自动修复字段：{field}")
    
    # 验证 status 值
    if "status" in card_data and card_data["status"] not in STATUS_VALUES:
        result["valid"] = False
        result["issues"].append(
            f"status 值无效：{card_data['status']}，应为 {STATUS_VALUES} 之一"
        )
        if fix:
            card_data["status"] = "planning"
            result["fixed"] = True
    
    # 验证数字范围
    if "current_chapter" in card_data and card_data["current_chapter"] < 0:
        result["valid"] = False
        result["issues"].append("current_chapter 不能为负数")
        if fix:
            card_data["current_chapter"] = 0
            result["fixed"] = True
    
    if "target_chapters" in card_data and card_data["target_chapters"] < 0:
        result["valid"] = False
        result["issues"].append("target_chapters 不能为负数")
        if fix:
            card_data["target_chapters"] = 0
            result["fixed"] = True
    
    # 写入修复后的文件
    if fix and result["fixed"]:
        with open(card_path, "w", encoding="utf-8") as f:
            json.dump(card_data, f, ensure_ascii=False, indent=2)
        result["content"] = card_data
    
    # 生成报告
    if result["valid"] and not result["fixed"]:
        report = f"[OK] card.json 验证通过\n\n路径：{card_path}\n\n内容：\n{json.dumps(card_data, ensure_ascii=False, indent=2)}"
        elapsed = time.time() - start_time
        logger.info("[card_validator] <<< 验证通过 | card_path=%s | issues_count=0 | 耗时=%.3fs", card_path, elapsed)
    elif result["fixed"]:
        report = f"[FIXED] card.json 已修复\n\n路径：{card_path}\n\n问题：\n" + "\n".join(
            f"- {issue}" for issue in result["issues"]
        ) + f"\n\n修复后内容：\n{json.dumps(card_data, ensure_ascii=False, indent=2)}"
        elapsed = time.time() - start_time
        logger.info("[card_validator] <<< 已修复 | card_path=%s | issues_count=%d | 耗时=%.3fs", card_path, len(result["issues"]), elapsed)
    else:
        report = f"[FAIL] card.json 验证失败\n\n路径：{card_path}\n\n问题：\n" + "\n".join(
            f"- {issue}" for issue in result["issues"]
        ) + "\n\n建议：设置 fix=True 可自动修复"
        elapsed = time.time() - start_time
        logger.warning("[card_validator] <<< 验证失败 | card_path=%s | issues_count=%d | 耗时=%.3fs", card_path, len(result["issues"]), elapsed)

    return report
