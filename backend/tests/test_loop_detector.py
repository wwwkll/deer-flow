"""Unit tests for ``deerflow.models.loop_detector.StreamLoopDetector``.

Focus areas:
* Layer A — exact n-gram suffix repetition (短语循环).
* Layer B — clause-skeleton similarity repetition (模板变体循环).
* Negative cases — long-form prose must NOT trip the detector.
* Behavior knobs — ``enabled=False`` and ``min_content_length`` warm-up.
"""

from __future__ import annotations

import pytest

from deerflow.models.loop_detector import (
    LoopDetectorConfig,
    StreamLoopDetector,
    _char_bigrams,
    _dice,
    _split_clauses,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _feed_text(detector: StreamLoopDetector, text: str, chunk_size: int = 12):
    """Stream *text* into *detector* one chunk at a time, mimicking SSE deltas.

    Returns the first ``LoopDetectionResult`` whose ``detected`` is True, or
    the last non-detected result if no loop was found.
    """
    last = None
    for i in range(0, len(text), chunk_size):
        last = detector.feed(text[i : i + chunk_size])
        if last.detected:
            return last
    return last


# ---------------------------------------------------------------------------
# Layer A — exact n-gram repetition
# ---------------------------------------------------------------------------


class TestNgramRepetition:
    def test_detects_short_phrase_exact_loop(self):
        """Type-A loop: model repeats the same 2-char phrase forever.

        With ngram_sizes=[12,24,48] the smallest n is 12, so the suffix
        will be a 12-char window of the repeating pattern (e.g. "好的好的好的好的").
        This still catches the loop because the 12-char window repeats.
        """
        detector = StreamLoopDetector(LoopDetectorConfig(min_content_length=50, check_interval_chars=10, max_ngram_repeats=4))
        text = "正在分析问题：" + "好的好的" * 60
        result = _feed_text(detector, text)
        assert result.detected, f"expected detection, got {result}"
        assert result.layer == "ngram"

    def test_detects_sentence_length_exact_loop(self):
        """Type-A loop with a longer 12-char repeating sentence."""
        detector = StreamLoopDetector(LoopDetectorConfig(min_content_length=100, check_interval_chars=20))
        sentence = "我是一个智能助手帮你"  # 10 chars
        text = "Hi there. " + (sentence + "。") * 35
        result = _feed_text(detector, text, chunk_size=15)
        assert result.detected
        assert result.layer in ("ngram", "clause")

    def test_min_content_length_warmup_prevents_early_false_positive(self):
        """A short reply that happens to repeat shouldn't trigger detection."""
        # min_content_length=200 means we must see >=200 chars before checking
        detector = StreamLoopDetector(LoopDetectorConfig(min_content_length=200, check_interval_chars=30))
        text = "好的好的好的好的好的"  # only 10 chars — under warmup
        result = _feed_text(detector, text)
        assert result is None or not result.detected

    def test_no_detection_on_normal_prose(self):
        """A long-form, varied paragraph must NOT trigger the n-gram check."""
        detector = StreamLoopDetector(LoopDetectorConfig(min_content_length=100, check_interval_chars=30))
        prose = (
            "在二十一世纪的早晨，一只小狗在公园里追逐着飘落的枫叶。它的主人坐在长椅上读书，"
            "偶尔抬头看向远方的湖面。湖面平静如镜，倒映着对岸的高楼大厦和淡蓝色的天空。"
            "微风吹过，水面泛起层层涟漪，将倒影揉碎成无数闪烁的光点。一群白鸽飞过，"
            "在水面上投下短暂的阴影。这是一个普通而美好的早晨，城市还没有完全苏醒，"
            "街道上行人稀少，整个世界都像是被柔软的光线包裹着。"
        )
        result = _feed_text(detector, prose)
        assert result is None or not result.detected, f"false positive on normal prose: {result}"

    def test_detects_english_phrase_loop(self):
        """Non-Chinese loops must also be caught."""
        detector = StreamLoopDetector(LoopDetectorConfig(min_content_length=100, check_interval_chars=20, max_ngram_repeats=4))
        text = "Working on your request now. " + "I am sorry I am sorry " * 30
        result = _feed_text(detector, text)
        assert result.detected
        assert result.layer == "ngram"


# ---------------------------------------------------------------------------
# Layer B — clause-skeleton similarity repetition
# ---------------------------------------------------------------------------


class TestClauseRepetition:
    def test_detects_templated_weekday_loop(self):
        """The canonical Type-B loop the user described."""
        detector = StreamLoopDetector(
            LoopDetectorConfig(
                min_content_length=40,
                check_interval_chars=10,
                # Make sure layer A doesn't snipe this — keep it small enough
                max_ngram_repeats=10,
            )
        )
        text = (
            "让我帮你算一算未来几天的安排。"
            "今天是周一，明天是周二，三天后是周三，四天后是周四，"
            "五天后是周五，六天后是周六，七天后是周日。"
        )
        result = _feed_text(detector, text)
        assert result is not None and result.detected, f"expected clause-loop detection, got {result}"
        # The clause layer should win (or at minimum, *something* fires)
        # Both layers are acceptable since the pattern is also somewhat exact.
        assert result.layer in {"clause", "ngram"}

    def test_detects_templated_listing_loop(self):
        """Another Type-B: enumerating items with shared structure."""
        detector = StreamLoopDetector(
            LoopDetectorConfig(
                min_content_length=40,
                check_interval_chars=10,
                max_ngram_repeats=10,
                clause_similarity_threshold=0.5,
                max_clause_repeats=4,
            )
        )
        text = (
            "我可以为你提供如下功能。"
            "你可以问问题，"
            "你可以查资料，"
            "你可以写代码，"
            "你可以做翻译，"
            "你可以画图表，"
            "你可以读文件。"
        )
        result = _feed_text(detector, text)
        assert result is not None and result.detected
        assert result.layer == "clause"

    def test_long_prose_with_one_anaphora_not_flagged(self):
        """A real paragraph that begins each sentence with 「他」 but is
        otherwise different content must NOT trigger clause repetition."""
        detector = StreamLoopDetector(LoopDetectorConfig(min_content_length=100, check_interval_chars=30))
        text = (
            "他走进了房间。"
            "他打开窗户让阳光照进来。"
            "他煮了一壶咖啡静静地等待客人到来。"
            "屋里飘着浓郁的咖啡香气和远处传来的钢琴声。"
            "壁炉里柴火噼啪作响而墙上的钟敲过了八下。"
            "他知道今天将会是一个值得纪念的日子。"
        )
        result = _feed_text(detector, text)
        assert result is None or not result.detected


# ---------------------------------------------------------------------------
# Toggles / edge cases
# ---------------------------------------------------------------------------


class TestToggles:
    def test_disabled_detector_never_fires(self):
        detector = StreamLoopDetector(LoopDetectorConfig(enabled=False))
        text = "好的好的好的好的好的" * 200
        result = _feed_text(detector, text)
        assert result is None or not result.detected
        assert detector.total_chars == 0  # disabled fast-path skips feeding

    def test_empty_chunks_are_safe(self):
        detector = StreamLoopDetector(LoopDetectorConfig(min_content_length=10))
        for _ in range(10):
            result = detector.feed("")
            assert not result.detected

    def test_check_interval_throttles_work(self):
        """Detection runs only every ``check_interval_chars`` chars.

        We feed 100 chars in a single chunk past the threshold and the
        detector should run exactly once (state should advance correctly).
        """
        detector = StreamLoopDetector(LoopDetectorConfig(min_content_length=50, check_interval_chars=50))
        # First feed: 60 chars, > min_content_length and > check_interval → runs once
        detector.feed("a" * 60)
        # Second feed: 10 chars — under check_interval, no run
        result = detector.feed("a" * 10)
        assert not result.detected

    def test_repeated_single_character_is_detected_via_smallest_ngram(self):
        """Pathological "aaaaaa..." should still be caught.

        With ngram_sizes=[12,24,48] the smallest n is 12.  A run of 200
        'a' chars produces a 12-char suffix of 'aaaaaaaaaaaa' which
        repeats many times in the tail buffer.
        """
        detector = StreamLoopDetector(LoopDetectorConfig(min_content_length=50, check_interval_chars=10, max_ngram_repeats=4))
        text = "Some intro text here. " + "a" * 200
        result = _feed_text(detector, text)
        assert result.detected
        assert result.layer == "ngram"


# ---------------------------------------------------------------------------
# Helpers — verify the math primitives directly
# ---------------------------------------------------------------------------


class TestPrimitives:
    def test_char_bigrams_basic(self):
        assert _char_bigrams("abcd") == frozenset({"ab", "bc", "cd"})
        assert _char_bigrams("a") == frozenset()
        assert _char_bigrams("") == frozenset()

    @pytest.mark.parametrize(
        "a,b,expected_range",
        [
            ("今天是周一", "明天是周二", (0.4, 0.7)),  # high structural overlap
            ("hello", "world", (0.0, 0.1)),  # no bigram overlap
            ("identical", "identical", (1.0, 1.0)),
            ("abcd", "abcd", (1.0, 1.0)),
        ],
    )
    def test_dice_similarity(self, a, b, expected_range):
        d = _dice(_char_bigrams(a), _char_bigrams(b))
        lo, hi = expected_range
        assert lo <= d <= hi, f"dice({a!r}, {b!r}) = {d:.3f} not in [{lo}, {hi}]"

    def test_split_clauses_skips_short_and_long(self):
        text = "A。这是一个正常长度的子句。短。" + "x" * 100 + "。最后一个子句。"
        clauses = _split_clauses(text, min_length=3, max_length=20)
        # "A" too short, "短" too short, the 100-char one too long
        assert "这是一个正常长度的子句" in clauses
        assert "最后一个子句" in clauses
        assert "短" not in clauses
        assert not any(len(c) > 20 for c in clauses)
