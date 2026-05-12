"""回归测试：_resolve_context_window 必须按当前 agent 的模型来解析窗口大小

之前的 bug：永远只看 ``app_config.models[0]``。后果是：
- 如果你的对话用 mimo-v2-omni（200K 窗口），但 models[0] 是 qwen-3-6-online（32K）
  → SummarizationMiddleware 在对话才到 27K token 时就压缩历史，浪费模型 170K 的剩余空间
- 反过来如果 models[0] 窗口大、实际用的小 → 该压缩没压缩，到模型上限时直接报错

修复后必须：
- T1: 传入 model_name → 用该模型的 context_window
- T2: 传入未知 model_name → 退化到 models[0]（不破坏旧调用方）
- T3: 传入 None → 退化到 models[0]
- T4: 模型没配 context_window → 触发 base_url 自动探测
- T5: 模型没配 context_window 且没 base_url → 用默认 32768
"""

import sys
import os
from unittest.mock import patch, MagicMock
from dataclasses import dataclass, field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend', 'packages', 'harness'))

from deerflow.agents.lead_agent.agent import _resolve_context_window, _auto_detect_context_window


@dataclass
class FakeModel:
    name: str
    context_window: int | None = None
    base_url: str | None = None


@dataclass
class FakeAppConfig:
    models: list = field(default_factory=list)

    def get_model_config(self, name: str):
        for m in self.models:
            if m.name == name:
                return m
        return None


def _patch_app_config(models):
    return patch(
        "deerflow.agents.lead_agent.agent.get_app_config",
        return_value=FakeAppConfig(models=models),
    )


def setup_function(_):
    _auto_detect_context_window.cache_clear()


def test_per_agent_model_window_used():
    """T1: 指定 model_name 时按该模型的 context_window 返回"""
    print("\n=== T1 按当前 agent 模型解析窗口 ===")
    setup_function(None)
    models = [
        FakeModel(name="qwen-3-6-online", context_window=32768),
        FakeModel(name="mimo-v2-omni", context_window=200000),
        FakeModel(name="qwen-3-6-local", context_window=70000),
    ]
    with _patch_app_config(models):
        # 关键：用第二个模型，应该返回 200K，而不是 models[0] 的 32K
        result = _resolve_context_window("mimo-v2-omni")
        assert result == 200000, f"应返回 200000（mimo-v2-omni），实际 {result}"

        # 同样的配置，agent 用 qwen-3-6-local
        result2 = _resolve_context_window("qwen-3-6-local")
        assert result2 == 70000, f"应返回 70000，实际 {result2}"
    print(f"PASS  -> mimo-v2-omni → 200000, qwen-3-6-local → 70000")


def test_unknown_model_falls_back_to_first():
    """T2: 未知 model_name 不抛异常，退化到 models[0]"""
    print("\n=== T2 未知模型退化到 models[0] ===")
    setup_function(None)
    models = [
        FakeModel(name="default-model", context_window=8192),
        FakeModel(name="other", context_window=99999),
    ]
    with _patch_app_config(models):
        result = _resolve_context_window("does-not-exist")
        assert result == 8192, f"未知模型应退化到 models[0]=8192，实际 {result}"
    print(f"PASS  -> 未知模型 → models[0].context_window=8192")


def test_none_model_name_falls_back_to_first():
    """T3: 传 None 时也退化到 models[0]（向后兼容）"""
    print("\n=== T3 None 退化到 models[0] ===")
    setup_function(None)
    models = [FakeModel(name="default-model", context_window=16384)]
    with _patch_app_config(models):
        result = _resolve_context_window(None)
        assert result == 16384
        # 不传参数也行
        result2 = _resolve_context_window()
        assert result2 == 16384
    print(f"PASS  -> None / 无参数 → models[0].context_window=16384")


def test_no_context_window_triggers_auto_detect():
    """T4: 模型没配 context_window 时触发 base_url 自动探测"""
    print("\n=== T4 缺 context_window → 自动探测 base_url ===")
    setup_function(None)
    models = [
        FakeModel(name="online", context_window=32768),
        FakeModel(name="local-no-window", context_window=None, base_url="http://localhost:1234/v1"),
    ]
    fake_resp_body = b'{"data":[{"context_length":40960}]}'
    fake_resp = MagicMock()
    fake_resp.__enter__ = MagicMock(return_value=fake_resp)
    fake_resp.__exit__ = MagicMock(return_value=False)
    fake_resp.read = MagicMock(return_value=fake_resp_body)

    with _patch_app_config(models), patch("urllib.request.urlopen", return_value=fake_resp):
        result = _resolve_context_window("local-no-window")
        assert result == 40960, f"应从 /models 探测到 40960，实际 {result}"
    print(f"PASS  -> local-no-window → auto-detect → 40960")


def test_no_window_no_base_url_returns_default():
    """T5: 模型既没 context_window 也没 base_url → 返回默认 32768"""
    print("\n=== T5 完全缺信息 → 默认 32768 ===")
    setup_function(None)
    models = [FakeModel(name="bare", context_window=None, base_url=None)]
    with _patch_app_config(models):
        result = _resolve_context_window("bare")
        assert result == 32768, f"应返回默认 32768，实际 {result}"
    print(f"PASS  -> 无 context_window 无 base_url → 默认 32768")


def test_per_agent_does_not_use_models_zero_when_target_found():
    """T6 (核心回归)：目标模型有 context_window 时，绝不能落到 models[0]"""
    print("\n=== T6 目标模型存在时不读 models[0]（核心回归）===")
    setup_function(None)
    # 模拟你的真实场景：models[0]=qwen 32K，但 agent 用 mimo 200K
    models = [
        FakeModel(name="qwen-3-6-online", context_window=32768),
        FakeModel(name="mimo-v2-omni", context_window=200000),
    ]
    with _patch_app_config(models):
        result = _resolve_context_window("mimo-v2-omni")
        # 关键断言：不能拿到 32768
        assert result != 32768, \
            f"不应再返回 models[0] 的 32768；说明又改回硬编码了。实际 {result}"
        assert result == 200000
    print(f"PASS  -> mimo-v2-omni 不再被 models[0]=32768 覆盖")


def main():
    tests = [
        test_per_agent_model_window_used,
        test_unknown_model_falls_back_to_first,
        test_none_model_name_falls_back_to_first,
        test_no_context_window_triggers_auto_detect,
        test_no_window_no_base_url_returns_default,
        test_per_agent_does_not_use_models_zero_when_target_found,
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
