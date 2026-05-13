"""card_updater + card_validator(time bug) 联合测试

覆盖：
1. card_validator 修复后能否走通 [OK] 路径（即不再 NameError on time）
2. card_updater 部分字段更新 / 跨字段一致性 / 错误参数 / 文件不存在等
"""

import sys
import os
import json
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from my_tools.card_validator import card_validator
from my_tools.card_updater import card_updater


def _make_card(path: str, **overrides):
    data = {
        "book_name": "测试小说",
        "genre": "玄幻",
        "concept": "测试概念",
        "platform": "起点",
        "status": "planning",
        "current_chapter": 0,
        "target_chapters": 0,
    }
    data.update(overrides)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data


def test_validator_no_longer_crashes_on_ok_path():
    """Bug 1 回归测试：合法 card.json 走 [OK] 路径不能再 NameError"""
    print("\n=== T1 validator OK 路径无 NameError ===")
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "card.json")
        _make_card(p)
        # 关键：fix=False 走 valid 且 not fixed 的成功分支（line 270-272，原崩溃点）
        result = card_validator.invoke({"card_path": p, "fix": False})
        assert "[OK]" in result, f"应返回 [OK]，实际：{result[:200]}"
        print("PASS")


def test_updater_basic_update():
    """更新 target_chapters，其他字段保持不变"""
    print("\n=== T2 updater 基本更新 ===")
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "card.json")
        original = _make_card(p, target_chapters=20)

        result = card_updater.invoke({
            "description": "用户要求一直写到35章",
            "card_path": p,
            "target_chapters": 35,
        })
        assert "[OK]" in result, f"更新应成功：{result[:300]}"
        assert "target_chapters: 20 -> 35" in result, f"变更日志缺失：{result[:300]}"

        with open(p, "r", encoding="utf-8") as f:
            after = json.load(f)
        assert after["target_chapters"] == 35
        # 其他字段不变
        for k in ("book_name", "genre", "concept", "platform", "status", "current_chapter"):
            assert after[k] == original[k], f"{k} 被意外修改：{after[k]} != {original[k]}"
        print("PASS")


def test_updater_multi_field():
    """同时更新多个字段：current_chapter + status"""
    print("\n=== T3 updater 多字段更新 ===")
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "card.json")
        _make_card(p, status="planning", current_chapter=0, target_chapters=10)

        result = card_updater.invoke({
            "description": "开始写作",
            "card_path": p,
            "status": "writing",
            "current_chapter": 1,
        })
        assert "[OK]" in result, result[:300]

        with open(p, "r", encoding="utf-8") as f:
            after = json.load(f)
        assert after["status"] == "writing"
        assert after["current_chapter"] == 1
        assert after["target_chapters"] == 10  # 未指定，保持不变
        print("PASS")


def test_updater_no_change_when_default():
    """所有参数都是默认值，应返回 [OK] 并附当前内容（避免 LLM 误判为错误）。

    行为变更（v2）：从 [FAIL] 改为 [OK]，因为"没传入字段"本身不是错误，
    LLM 收到 [FAIL] 会误判触发重试或开 bash。
    """
    print("\n=== T4 updater 无字段时友好返回 ===")
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "card.json")
        _make_card(p)

        result = card_updater.invoke({
            "description": "空更新",
            "card_path": p,
        })
        assert "[OK]" in result, f"应返回 [OK]：{result[:200]}"
        assert "未提供任何更新字段" in result
        print("PASS")


def test_updater_invalid_status():
    """非法 status 应被拒"""
    print("\n=== T5 updater 校验非法 status ===")
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "card.json")
        _make_card(p)

        result = card_updater.invoke({
            "description": "尝试非法状态",
            "card_path": p,
            "status": "garbage",
        })
        assert "[FAIL]" in result and "status 值无效" in result, result[:300]
        print("PASS")


def test_updater_negative_chapter_rejected():
    """负数章节号应被拒"""
    print("\n=== T6 updater 负数章节号 ===")
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "card.json")
        _make_card(p)

        result = card_updater.invoke({
            "description": "尝试负数",
            "card_path": p,
            "current_chapter": -5,  # -1 是 sentinel；其他负数应被拒
        })
        # -5 != -1，所以会进入更新分支并触发非负校验
        assert "[FAIL]" in result and "current_chapter 必须为非负整数" in result, result[:300]
        print("PASS")


def test_updater_current_exceeds_target():
    """current_chapter > target_chapters 不再拒绝，改为 OK + ⚠️ 警告。

    行为变更（v2）：旧版直接 FAIL 阻断了"current 已达原 target，准备同时拉高 target"
    这种正常工作流；改为允许写入并附警告，让 LLM 自行评估是否需要同时更新 target。
    """
    print("\n=== T7 updater 进度超过目标(警告而非拒绝) ===")
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "card.json")
        _make_card(p, current_chapter=5, target_chapters=10)

        result = card_updater.invoke({
            "description": "写过头",
            "card_path": p,
            "current_chapter": 15,  # > 10
        })
        assert "[OK]" in result, f"应允许写入：{result[:300]}"
        assert "警告" in result and "target_chapters 需要同时上调" in result, f"应附警告：{result[:300]}"
        # 实际值应被写入
        with open(p, "r", encoding="utf-8") as f:
            after = json.load(f)
        assert after["current_chapter"] == 15
        assert after["target_chapters"] == 10
        print("PASS")


def test_updater_file_not_exists():
    """文件不存在时应给出明确提示，不创建新文件"""
    print("\n=== T8 updater 文件不存在 ===")
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "missing.json")
        result = card_updater.invoke({
            "description": "更新不存在的文件",
            "card_path": p,
            "target_chapters": 10,
        })
        assert "[FAIL]" in result and "文件不存在" in result, result[:300]
        assert not os.path.exists(p), "card_updater 不应创建新文件"
        print("PASS")


def test_updater_no_actual_change():
    """传入值与原值相同时，应返回 OK 但说明无实际变更"""
    print("\n=== T9 updater 同值无实际变更 ===")
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "card.json")
        _make_card(p, target_chapters=20)

        result = card_updater.invoke({
            "description": "传入相同值",
            "card_path": p,
            "target_chapters": 20,
        })
        assert "[OK]" in result and "无实际变更" in result, result[:300]
        print("PASS")


def test_validator_updater_combo():
    """validator + updater 配合使用：先校验，再更新"""
    print("\n=== T10 validator + updater 联用 ===")
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "card.json")
        _make_card(p)

        v = card_validator.invoke({"card_path": p, "fix": False})
        assert "[OK]" in v, v[:300]

        u = card_updater.invoke({
            "description": "推进进度",
            "card_path": p,
            "current_chapter": 1,
            "status": "writing",
        })
        assert "[OK]" in u, u[:300]

        # 再校验一次确保仍合规
        v2 = card_validator.invoke({"card_path": p, "fix": False})
        assert "[OK]" in v2, v2[:300]
        print("PASS")


def test_updater_create_if_missing_fills_defaults():
    """缺 status 字段时，create_if_missing=True 应允许写入并自动补齐默认值。

    这是本次 v2 升级要解决的核心场景：原版会因为"必填字段缺失"拒绝写入，
    而 card_validator(fix=True) 也不补缺字段 —— 形成死循环，逼用户开 bash。
    """
    print("\n=== T11 updater 缺字段+create_if_missing 自动补齐 ===")
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "card.json")
        # 故意构造一个缺 status 的 card.json
        with open(p, "w", encoding="utf-8") as f:
            json.dump({
                "book_name": "测试",
                "genre": "玄幻",
                "concept": "概念",
                "platform": "起点",
                "current_chapter": 10,
                "target_chapters": 50,
                # 缺 status
            }, f)

        # 不带 create_if_missing → 应失败
        r1 = card_updater.invoke({
            "description": "尝试更新但缺 status",
            "card_path": p,
            "current_chapter": 11,
        })
        assert "[FAIL]" in r1 and "status" in r1, f"默认应拒绝缺字段：{r1[:300]}"

        # 带 create_if_missing=True → 应成功，且 status 被补成 "planning"
        r2 = card_updater.invoke({
            "description": "补齐缺失字段并推进章节",
            "card_path": p,
            "current_chapter": 11,
            "create_if_missing": True,
        })
        assert "[OK]" in r2, f"应成功：{r2[:300]}"
        assert "补齐缺失必填字段" in r2 and "status" in r2, f"应记录补齐：{r2[:300]}"

        with open(p, "r", encoding="utf-8") as f:
            after = json.load(f)
        assert after["status"] == "planning", f"status 应被补成 planning：{after}"
        assert after["current_chapter"] == 11
        # 原有字段保留
        assert after["book_name"] == "测试"
        print("PASS")


def test_updater_strict_default_cleans_extra_fields():
    """strict 默认 True：写回时清理非标准字段（如 novel_id、word_count）。"""
    print("\n=== T12 updater strict=True(默认) 清理非标准字段 ===")
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "card.json")
        # 构造含 7 个标准字段 + 5 个非标准字段的脏 card
        with open(p, "w", encoding="utf-8") as f:
            json.dump({
                "book_name": "脏数据测试",
                "genre": "玄幻",
                "concept": "概念",
                "platform": "起点",
                "status": "writing",
                "current_chapter": 5,
                "target_chapters": 50,
                # 以下应被清理
                "novel_id": "abc-123",
                "title": "重复字段",
                "created_at": "2024-01-01",
                "word_count": 12345,
                "extra_metadata": {"some": "garbage"},
            }, f)

        result = card_updater.invoke({
            "description": "推进章节顺手清理脏字段",
            "card_path": p,
            "current_chapter": 6,
        })
        assert "[OK]" in result, f"应成功：{result[:400]}"
        assert "清理非标准字段" in result, f"应记录清理：{result[:400]}"
        # 报告里应明确列出被删的键
        for k in ("novel_id", "title", "created_at", "word_count", "extra_metadata"):
            assert k in result, f"清理列表应包含 {k}：{result[:600]}"

        with open(p, "r", encoding="utf-8") as f:
            after = json.load(f)
        assert set(after.keys()) == set([
            "book_name", "genre", "concept", "platform",
            "status", "current_chapter", "target_chapters",
        ]), f"清理后应只剩 7 字段：{list(after.keys())}"
        assert after["current_chapter"] == 6
        print("PASS")


def test_updater_strict_false_keeps_extra_fields():
    """strict=False 时保留非标准字段（迁移/调试场景）。"""
    print("\n=== T13 updater strict=False 保留非标准字段 ===")
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "card.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump({
                "book_name": "测试",
                "genre": "玄幻",
                "concept": "概念",
                "platform": "起点",
                "status": "writing",
                "current_chapter": 5,
                "target_chapters": 50,
                "novel_id": "abc-123",
            }, f)

        result = card_updater.invoke({
            "description": "迁移期间暂时保留 novel_id",
            "card_path": p,
            "current_chapter": 6,
            "strict": False,
        })
        assert "[OK]" in result, f"应成功：{result[:300]}"
        assert "清理非标准字段" not in result, f"strict=False 不应清理：{result[:300]}"

        with open(p, "r", encoding="utf-8") as f:
            after = json.load(f)
        assert "novel_id" in after, f"novel_id 应保留：{after}"
        assert after["current_chapter"] == 6
        print("PASS")


def test_updater_no_field_with_dirty_card_triggers_cleanup():
    """没传任何更新字段，但 card 有非标准字段时，strict=True 仍应触发清理。"""
    print("\n=== T14 updater 仅清理（无字段更新） ===")
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "card.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump({
                "book_name": "测试",
                "genre": "玄幻",
                "concept": "概念",
                "platform": "起点",
                "status": "writing",
                "current_chapter": 5,
                "target_chapters": 50,
                "junk": "x",
            }, f)

        result = card_updater.invoke({
            "description": "仅清理脏字段",
            "card_path": p,
        })
        assert "[OK]" in result, f"应成功：{result[:300]}"
        assert "清理非标准字段" in result and "junk" in result, f"应清理：{result[:300]}"

        with open(p, "r", encoding="utf-8") as f:
            after = json.load(f)
        assert "junk" not in after
        print("PASS")


def main():
    tests = [
        test_validator_no_longer_crashes_on_ok_path,
        test_updater_basic_update,
        test_updater_multi_field,
        test_updater_no_change_when_default,
        test_updater_invalid_status,
        test_updater_negative_chapter_rejected,
        test_updater_current_exceeds_target,
        test_updater_file_not_exists,
        test_updater_no_actual_change,
        test_validator_updater_combo,
        test_updater_create_if_missing_fills_defaults,
        test_updater_strict_default_cleans_extra_fields,
        test_updater_strict_false_keeps_extra_fields,
        test_updater_no_field_with_dirty_card_triggers_cleanup,
    ]
    failed = []
    for t in tests:
        try:
            t()
        except Exception as e:
            import traceback
            traceback.print_exc()
            failed.append((t.__name__, str(e)))

    print("\n" + "=" * 60)
    if failed:
        print(f"[FAIL] {len(failed)}/{len(tests)} 测试失败：")
        for name, err in failed:
            print(f"  - {name}: {err}")
        sys.exit(1)
    else:
        print(f"[OK] 全部 {len(tests)} 项测试通过")


if __name__ == "__main__":
    main()
