"""StreamLoopDetector — detect LLM output loops during streaming.

Small / local models (Qwen / DeepSeek / Yi-Lite 等) sometimes get stuck and
produce the same content forever:

  Type A — exact repetition / short phrase repetition::

      好的好的好的好的好的好的好的好的好的好的好的好的好的

  Type B — templated variation repetition::

      今天是周一，明天是周二，三天后是周三，四天后是周四，五天后是周五……

This module provides ``StreamLoopDetector`` that accumulates streamed text
chunks and reports the first moment a loop is detected.

Algorithm
=========

The detector keeps a rolling **tail** buffer of the most recent
``max_tail_chars`` characters and runs two complementary checks each time the
amount of new text since the previous check exceeds ``check_interval_chars``:

Layer A — Suffix n-gram repetition (catches *Type A*)
    For each n in ``ngram_sizes`` (e.g. ``[6, 12, 24, 48]``) take the last *n*
    characters of the buffer (the most recently emitted pattern) and count
    how many times it appears in the tail buffer.  When the count for any
    size reaches ``max_ngram_repeats``, declare a loop.

Layer B — Clause skeleton repetition (catches *Type B*)
    Split the tail buffer by Chinese / English punctuation (``。！？，,;.!?``
    and newlines) into clauses.  For each clause keep its character bigram
    set.  For the most recent clause, count how many of the preceding
    ``clause_window`` clauses have a Sørensen–Dice similarity above
    ``clause_similarity_threshold``.  When that count reaches
    ``max_clause_repeats``, declare a loop.

Both checks honour a ``min_content_length`` warm-up threshold to avoid false
positives on short prefixes such as ``"# Heading\n\n"`` or ``"OK."``.

The detector is intentionally O(tail_size * ngram_count) per check.  Since
checks run at most once per ``check_interval_chars`` (default 60), the cost
is small relative to LLM-side latency.
"""

from __future__ import annotations

import logging
import re
from collections import deque
from dataclasses import dataclass, field
from typing import Iterable

logger = logging.getLogger(__name__)

# Clause delimiters covering Chinese, English, and structural breaks.
# We deliberately treat commas as clause boundaries because templated loops
# like "今天是周一，明天是周二" are best inspected at the comma-clause level.
_CLAUSE_DELIMITERS = "。！？!?；;\n\r\t，,"
_CLAUSE_SPLIT_RE = re.compile(f"[{re.escape(_CLAUSE_DELIMITERS)}]+")

# Whitespace and punctuation we strip when comparing clause skeletons.
_CLAUSE_NOISE_RE = re.compile(r"[\s　\"'`、（）()\[\]{}<>《》—\-_/\\|*~`]+")


@dataclass
class LoopDetectionResult:
    """Result of a single ``check`` call.

    Attributes:
        detected: True if a loop was detected.
        reason: Human-readable explanation, e.g.
            ``"exact n-gram '好的' repeated 8 times in tail"``.
        layer: ``"ngram"`` or ``"clause"`` — which detector fired.
        pattern: The repeating fragment (for logging / user-facing messages).
        repeat_count: How many repetitions were observed.
    """

    detected: bool = False
    reason: str = ""
    layer: str = ""
    pattern: str = ""
    repeat_count: int = 0


@dataclass
class LoopDetectorConfig:
    """Tuning knobs for ``StreamLoopDetector``.

    All thresholds have sensible defaults tuned for Chinese + English mixed
    content typical of DeerFlow chats.  The defaults are deliberately
    conservative — we'd rather miss a slow loop than abort a legitimate
    paragraph that happens to repeat a phrase a few times.
    """

    enabled: bool = True

    # Buffer sizing
    max_tail_chars: int = 2000
    """Sliding window of characters kept for analysis."""

    check_interval_chars: int = 60
    """Run detection every N newly-appended characters.  Smaller = more CPU
    but earlier detection; larger = cheaper but later detection."""

    min_content_length: int = 200
    """Don't even run detection until at least this much text has been
    streamed.  Prevents false positives on tiny replies like ``"OK"``."""

    # Layer A — exact n-gram suffix repetition
    ngram_sizes: tuple[int, ...] = (6, 12, 24, 48)
    """Suffix lengths to check.  Each tries to detect a different loop
    period: 6 for "好的好的"-style tight loops, 48 for paragraph-length
    repetition."""

    max_ngram_repeats: int = 30
    """Number of times the suffix n-gram must repeat in the tail before
    flagging a loop."""

    # Layer B — clause-skeleton repetition (templated variation)
    clause_window: int = 32
    """How many recent clauses to inspect.  Must be large enough to span
    multiple rotation cycles of a multi-block template loop (e.g. a
    4-step reasoning cycle needs window >> 4 * clauses_per_step)."""

    max_clause_repeats: int = 4
    """How many clauses in the window must be similar to the most recent
    one before flagging."""

    clause_similarity_threshold: float = 0.5
    """Dice coefficient threshold on character bigrams for two clauses to be
    considered structurally similar."""

    clause_min_length: int = 3
    """Ignore clauses shorter than this (no signal in 1-2 char fragments)."""

    clause_max_length: int = 80
    """Ignore very long clauses (likely real prose, not templated)."""

    def normalized_ngram_sizes(self) -> tuple[int, ...]:
        sizes = tuple(sorted({n for n in self.ngram_sizes if n >= 2}))
        return sizes or (6, 12, 24)


class StreamLoopDetector:
    """Stateful detector — feed it streamed chunks via :meth:`feed`.

    Usage::

        detector = StreamLoopDetector(LoopDetectorConfig())
        for chunk in stream:
            result = detector.feed(chunk)
            if result.detected:
                logger.warning("Loop: %s", result.reason)
                break

    Thread-safety: not thread-safe.  Each call/stream should own its own
    detector instance.
    """

    def __init__(self, config: LoopDetectorConfig | None = None) -> None:
        self.config = config or LoopDetectorConfig()
        self._tail: deque[str] = deque(maxlen=self.config.max_tail_chars)
        self._total_chars: int = 0
        self._chars_since_check: int = 0
        # Cached so we don't re-sort on every feed
        self._ngram_sizes = self.config.normalized_ngram_sizes()
        # Memoize last computed clause bigram fingerprints
        # (clause_text -> frozenset[bigram]); cleared when tail rotates a lot.
        self._bigram_cache: dict[str, frozenset[str]] = {}

    @property
    def total_chars(self) -> int:
        return self._total_chars

    def feed(self, chunk: str) -> LoopDetectionResult:
        """Append a streamed chunk and run detection if due.

        Returns a :class:`LoopDetectionResult`.  When ``detected`` is False
        the other fields are empty.

        If detection is disabled via config, this is a no-op that always
        returns a non-detected result.
        """
        if not self.config.enabled or not chunk:
            return LoopDetectionResult()

        self._tail.extend(chunk)
        self._total_chars += len(chunk)
        self._chars_since_check += len(chunk)

        if self._total_chars < self.config.min_content_length:
            return LoopDetectionResult()

        if self._chars_since_check < self.config.check_interval_chars:
            return LoopDetectionResult()

        self._chars_since_check = 0
        return self._check()

    def _tail_text(self) -> str:
        return "".join(self._tail)

    def _check(self) -> LoopDetectionResult:
        tail = self._tail_text()
        if not tail:
            return LoopDetectionResult()

        # Layer A — exact n-gram suffix repetition
        result = self._check_ngram_repetition(tail)
        if result.detected:
            return result

        # Layer B — clause skeleton repetition
        result = self._check_clause_repetition(tail)
        if result.detected:
            return result

        return LoopDetectionResult()

    # ------------------------------------------------------------------
    # Layer A — n-gram suffix repetition
    # ------------------------------------------------------------------

    def _check_ngram_repetition(self, tail: str) -> LoopDetectionResult:
        """Detect exact-string loops by suffix n-gram counting.

        Idea: the most recently emitted ``n`` characters are necessarily the
        head of any active loop.  If that suffix appears many times in the
        tail buffer, the model is stuck.  We check several values of ``n``
        so a short loop ("好的") and a long loop (a 40-char sentence) are
        both caught.
        """
        max_count = 0
        winner_pattern = ""
        winner_n = 0

        for n in self._ngram_sizes:
            if len(tail) < n * self.config.max_ngram_repeats:
                # Cannot possibly repeat that many times yet
                continue
            suffix = tail[-n:]
            # Skip suffixes that are pure whitespace — those are not loops.
            if not suffix.strip():
                continue
            # Skip degenerate suffixes built from a single character: they
            # collapse to "aaaa..." and would always over-count.  The smaller
            # n already covers that case.
            if len(set(suffix)) <= 1 and n > self._ngram_sizes[0]:
                continue

            count = self._count_non_overlapping(tail, suffix)
            if count > max_count:
                max_count = count
                winner_pattern = suffix
                winner_n = n

        if max_count >= self.config.max_ngram_repeats:
            preview = _shorten_for_log(winner_pattern)
            return LoopDetectionResult(
                detected=True,
                reason=f"exact pattern (n={winner_n}) {preview!r} repeated {max_count} times in last {len(tail)} chars",
                layer="ngram",
                pattern=winner_pattern,
                repeat_count=max_count,
            )
        return LoopDetectionResult()

    @staticmethod
    def _count_non_overlapping(text: str, pattern: str) -> int:
        """Count *non-overlapping* occurrences of ``pattern`` in ``text``.

        ``str.count`` already does this in CPython; we keep the helper to
        make intent explicit and easier to swap for an overlapping
        implementation later if needed.
        """
        if not pattern:
            return 0
        return text.count(pattern)

    # ------------------------------------------------------------------
    # Layer B — clause skeleton repetition
    # ------------------------------------------------------------------

    def _check_clause_repetition(self, tail: str) -> LoopDetectionResult:
        """Detect templated-variation loops by clause-level Dice similarity.

        Example we want to catch::

            今天是周一，明天是周二，三天后是周三，四天后是周四，五天后是周五……
            你可以问问题，你可以查资料，你可以写代码，你可以做翻译……

        Each clause is short and different in text, but they share most of
        the same characters / bigrams.  We use a **hybrid similarity** = the
        max of two Dice coefficients:

        * **Character bigram Dice** — order-sensitive; catches patterns whose
          *structure* repeats (e.g. ``"今天是周一"`` ↔ ``"明天是周二"``).
        * **Character set Dice** — order-insensitive; catches patterns where
          most clauses share the same vocabulary but only the *tail* word
          varies (e.g. ``"你可以问问题"`` ↔ ``"你可以查资料"`` — only two
          bigrams overlap, but three characters do).

        Taking the max means either signal is enough to fire — short
        Chinese-style templated lists that bigram-Dice misses are still
        caught via the character-set path.
        """
        clauses = _split_clauses(
            tail,
            min_length=self.config.clause_min_length,
            max_length=self.config.clause_max_length,
        )
        if len(clauses) < self.config.max_clause_repeats:
            return LoopDetectionResult()

        window = clauses[-self.config.clause_window :]
        if len(window) < self.config.max_clause_repeats:
            return LoopDetectionResult()

        # Refresh fingerprint caches for this window only — cheaper than
        # caching everything seen so far.  Pre-compute both bigram set and
        # character set per clause so the inner loop is just set arithmetic.
        self._bigram_cache = {c: _char_bigrams(c) for c in window}
        char_cache: dict[str, frozenset[str]] = {c: frozenset(c) for c in window}

        latest = window[-1]
        latest_bigrams = self._bigram_cache[latest]
        latest_chars = char_cache[latest]
        if not latest_bigrams and not latest_chars:
            return LoopDetectionResult()

        threshold = self.config.clause_similarity_threshold
        similar_count = 1  # latest counts as one occurrence
        for prev in window[:-1]:
            sim_bigram = _dice(latest_bigrams, self._bigram_cache[prev])
            sim_char = _dice(latest_chars, char_cache[prev])
            if max(sim_bigram, sim_char) >= threshold:
                similar_count += 1

        if similar_count >= self.config.max_clause_repeats:
            preview = _shorten_for_log(latest)
            return LoopDetectionResult(
                detected=True,
                reason=f"templated clause {preview!r} repeated {similar_count} times in last {len(window)} clauses (Dice ≥ {threshold})",
                layer="clause",
                pattern=latest,
                repeat_count=similar_count,
            )
        return LoopDetectionResult()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _split_clauses(text: str, *, min_length: int, max_length: int) -> list[str]:
    """Split *text* into clause candidates, normalized for comparison.

    The returned strings have whitespace and common punctuation removed so
    that ``"今天是周一"`` and ``"  今天是周一  "`` collapse to the same
    skeleton.  Empty / too-short / too-long clauses are dropped.
    """
    raw = _CLAUSE_SPLIT_RE.split(text)
    clauses: list[str] = []
    for fragment in raw:
        normalized = _CLAUSE_NOISE_RE.sub("", fragment).lower()
        if min_length <= len(normalized) <= max_length:
            clauses.append(normalized)
    return clauses


def _char_bigrams(text: str) -> frozenset[str]:
    """Return character bigrams of *text* as a frozenset.

    Bigrams capture word/clause structure better than single characters
    because they're sensitive to character order — "周一是今天" and
    "今天是周一" share many characters but few bigrams.
    """
    if len(text) < 2:
        return frozenset()
    return frozenset(text[i : i + 2] for i in range(len(text) - 1))


def _dice(a: Iterable[str], b: Iterable[str]) -> float:
    """Sørensen–Dice coefficient between two iterables of hashable items.

    ``2 * |A ∩ B| / (|A| + |B|)``  — symmetric, in ``[0, 1]``, more
    forgiving than Jaccard for short clauses.
    """
    set_a = a if isinstance(a, (set, frozenset)) else set(a)
    set_b = b if isinstance(b, (set, frozenset)) else set(b)
    total = len(set_a) + len(set_b)
    if total == 0:
        return 0.0
    return 2 * len(set_a & set_b) / total


def _shorten_for_log(text: str, max_len: int = 40) -> str:
    """Trim *text* for inclusion in log messages / error strings."""
    text = text.replace("\n", "\\n")
    if len(text) <= max_len:
        return text
    return text[:max_len] + "…"


__all__ = [
    "LoopDetectionResult",
    "LoopDetectorConfig",
    "StreamLoopDetector",
]
