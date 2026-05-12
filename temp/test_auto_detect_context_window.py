"""回归测试：_auto_detect_context_window 必须缓存结果 + 用 1 秒 timeout

修复前的 bug：
- 没有任何缓存 → 每次 /threads/{id}/history 都同步重新探测 base_url/models
- timeout 写死 5 秒 → 前端切对话延迟一致 5006ms
- 同步 urllib.urlopen 阻塞 FastAPI event loop → 并发请求互相串行

本测试覆盖：
- T1: 成功返回时只调用一次底层 urlopen（缓存生效）
- T2: 失败返回时也只调用一次（避免反复 timeout 5 秒）
- T3: 不同 base_url 各自缓存，不串扰
- T4: timeout 参数实际是 1 秒（防止下次有人不小心改回 5）
"""

import sys
import os
import time
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend', 'packages', 'harness'))

from deerflow.agents.lead_agent.agent import _auto_detect_context_window


def setup_function(_):
    """每个测试开始前清空 lru_cache，避免互相污染"""
    _auto_detect_context_window.cache_clear()


def test_success_path_caches_result():
    """成功返回 context_length 后，再次调用不应再发请求"""
    print("\n=== T1 成功结果被缓存 ===")
    setup_function(None)
    fake_resp_body = b'{"data":[{"context_length":40960}]}'
    fake_resp = MagicMock()
    fake_resp.__enter__ = MagicMock(return_value=fake_resp)
    fake_resp.__exit__ = MagicMock(return_value=False)
    fake_resp.read = MagicMock(return_value=fake_resp_body)

    with patch("urllib.request.urlopen", return_value=fake_resp) as mock_urlopen:
        ctx1 = _auto_detect_context_window("http://localhost:1234/v1")
        ctx2 = _auto_detect_context_window("http://localhost:1234/v1")
        ctx3 = _auto_detect_context_window("http://localhost:1234/v1")

        assert ctx1 == ctx2 == ctx3 == 40960, f"应返回 40960，实际 {ctx1}/{ctx2}/{ctx3}"
        assert mock_urlopen.call_count == 1, f"应只调用 1 次 urlopen，实际 {mock_urlopen.call_count}"
    print(f"PASS  -> 调用 3 次函数，底层 urlopen 仅触发 {mock_urlopen.call_count} 次")


def test_failure_path_also_caches():
    """请求失败（timeout/connection error）也要缓存 None，避免反复重试"""
    print("\n=== T2 失败结果也被缓存 ===")
    setup_function(None)
    with patch("urllib.request.urlopen", side_effect=TimeoutError("dummy")) as mock_urlopen:
        ctx1 = _auto_detect_context_window("https://broken.example.com/v1")
        ctx2 = _auto_detect_context_window("https://broken.example.com/v1")
        ctx3 = _auto_detect_context_window("https://broken.example.com/v1")

        assert ctx1 is None and ctx2 is None and ctx3 is None
        assert mock_urlopen.call_count == 1, \
            f"失败也只该探测 1 次（修复前会触发 3 次 5 秒 timeout = 15 秒），实际 {mock_urlopen.call_count}"
    print(f"PASS  -> 失败 endpoint 也仅探测 {mock_urlopen.call_count} 次")


def test_distinct_base_urls_cached_separately():
    """不同 base_url 的缓存条目应该独立"""
    print("\n=== T3 多 base_url 独立缓存 ===")
    setup_function(None)
    body_a = b'{"data":[{"context_length":8192}]}'
    body_b = b'{"data":[{"context_length":131072}]}'

    def fake_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req.get_full_url()
        m = MagicMock()
        m.__enter__ = MagicMock(return_value=m)
        m.__exit__ = MagicMock(return_value=False)
        if "endpoint-a" in url:
            m.read = MagicMock(return_value=body_a)
        else:
            m.read = MagicMock(return_value=body_b)
        return m

    with patch("urllib.request.urlopen", side_effect=fake_urlopen) as mock_urlopen:
        ctx_a = _auto_detect_context_window("http://endpoint-a/v1")
        ctx_b = _auto_detect_context_window("http://endpoint-b/v1")
        ctx_a_again = _auto_detect_context_window("http://endpoint-a/v1")
        ctx_b_again = _auto_detect_context_window("http://endpoint-b/v1")

        assert ctx_a == ctx_a_again == 8192
        assert ctx_b == ctx_b_again == 131072
        assert mock_urlopen.call_count == 2, f"应触发 2 次（两个 url 各 1 次），实际 {mock_urlopen.call_count}"
    print(f"PASS  -> 两个 url 共调用 {mock_urlopen.call_count} 次")


def test_timeout_param_is_one_second():
    """回归断言：timeout 实际值必须是 1 秒（防止再次改回 5）"""
    print("\n=== T4 timeout 参数 = 1 秒 ===")
    setup_function(None)

    captured: dict = {}

    def capture_timeout(req, timeout=None):
        captured["timeout"] = timeout
        raise TimeoutError("intentional")  # 模拟超时分支

    with patch("urllib.request.urlopen", side_effect=capture_timeout):
        result = _auto_detect_context_window("http://anywhere/v1")
        assert result is None
        assert captured.get("timeout") == 1, \
            f"timeout 必须为 1 秒（修复前是 5 秒），实际 {captured.get('timeout')}"
    print(f"PASS  -> 实际 timeout = {captured.get('timeout')} 秒")


def test_real_failure_is_fast():
    """端到端：探测一个保证不可达的地址，缓存命中后必须极快返回（<50ms）"""
    print("\n=== T5 缓存命中极快返回 ===")
    setup_function(None)
    bogus = "http://127.0.0.1:1/v1"  # 端口 1 必定拒绝/无人监听

    # 第一次：会真实超时一次（~1s）
    t0 = time.time()
    r1 = _auto_detect_context_window(bogus)
    elapsed_first = time.time() - t0
    assert r1 is None
    # 第二次：缓存命中，应该几乎瞬时
    t1 = time.time()
    r2 = _auto_detect_context_window(bogus)
    elapsed_second = time.time() - t1

    assert r2 is None
    assert elapsed_second < 0.05, \
        f"缓存命中必须 <50ms（修复前会再 timeout 1 秒），实际 {elapsed_second*1000:.1f}ms"
    # 第一次也不能超过 1.5 秒（timeout=1 + 一点 socket 开销容差）
    assert elapsed_first < 1.5, \
        f"首次调用最多 ~1 秒 timeout，实际 {elapsed_first*1000:.1f}ms"
    print(f"PASS  -> 首次 {elapsed_first*1000:.1f}ms，缓存后 {elapsed_second*1000:.3f}ms")


def main():
    tests = [
        test_success_path_caches_result,
        test_failure_path_also_caches,
        test_distinct_base_urls_cached_separately,
        test_timeout_param_is_one_second,
        test_real_failure_is_fast,
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
