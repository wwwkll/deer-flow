"""StreamLoopDetector — detect LLM output loops during streaming.

Small / local models (Qwen / DeepSeek / Yi-Lite 等) sometimes get stuck and
produce the same content forever:

  Type A — exact repetition / short phrase repetition::

      好的好的好的好的好的好的好的好的好的好的好的好的好的

  Type B — templated variation repetition::

      今天是周一，明天是周二，三天后是周三，四天后是周四，五天后是周五……

  Type C — large block / paragraph repetition::

      整段文字（数百到数千字符）被完整重复输出多次。
      例如 LLM 在 write_file 的 content 参数中把同一个场景重复写 10+ 遍。

This module provides ``StreamLoopDetector`` that accumulates streamed text
chunks and reports the first moment a loop is detected.

Algorithm
=========

The detector keeps a rolling **tail** buffer of the most recent
``max_tail_chars`` characters and runs three complementary checks each time the
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

Layer C — Paragraph fingerprint repetition (catches *Type C*)
    Split the tail buffer by paragraph boundaries (blank lines, ``……``,
    etc.) into paragraphs.  For each paragraph compute a fingerprint:
    exact-match via MD5 and fuzzy-match via character-set Dice similarity.
    When the same fingerprint appears ``max_paragraph_repeats`` times in the
    last ``paragraph_window`` paragraphs, declare a loop.

All checks honour a ``min_content_length`` warm-up threshold to avoid false
positives on short prefixes such as ``"# Heading\n\n"`` or ``"OK."``.

The detector is intentionally O(tail_size * ngram_count) per check.  Since
checks run at most once per ``check_interval_chars`` (default 60), the cost
is small relative to LLM-side latency.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections import Counter, deque
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
        layer: ``"ngram"``, ``"clause"``, or ``"paragraph"`` — which detector fired.
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
    max_tail_chars: int = 8000
    """Sliding window of characters kept for analysis.
    8000 chars ≈ 5000 tokens — large enough to hold 50 repetitions of a
    160-char loop cycle, ensuring we never miss a true infinite loop."""

    check_interval_chars: int = 200
    """Run detection every N newly-appended characters.  200 is a balanced
    trade-off — frequent enough for early detection, cheap enough on CPU."""

    min_content_length: int = 2000
    """Don't even run detection until at least this much text has been
    streamed.  Prevents false positives on short/medium replies.
    2000 chars ≈ 1300 tokens — we allow substantial output before checking."""

    # Layer A — exact n-gram suffix repetition
    ngram_sizes: tuple[int, ...] = (12, 24, 48)
    """Suffix lengths to check.  ``n=6`` is intentionally excluded — short
    n-grams like ``shared``, ``global``, ``hapter`` repeat frequently in
    normal prose / paths and cause false positives.  ``n=12`` is the
    shortest length that reliably distinguishes a loop from a repeated word."""

    max_ngram_repeats: int = 50
    """Number of times the suffix n-gram must repeat in the tail before
    flagging a loop.  50 is very permissive — a true infinite loop will
    hit this quickly, while normal prose with repeated phrases won't."""

    # Layer B — clause-skeleton repetition (templated variation)
    clause_window: int = 48
    """How many recent clauses to inspect.  Must be large enough to span
    multiple rotation cycles of a multi-block template loop (e.g. a
    4-step reasoning cycle needs window >> 4 * clauses_per_step)."""

    max_clause_repeats: int = 6
    """How many clauses in the window must be similar to the most recent
    one before flagging."""

    clause_similarity_threshold: float = 0.6
    """Dice coefficient threshold for two clauses to be considered
    structurally similar.  0.6 is stricter than 0.5, reducing false
    positives on naturally similar sentences."""

    clause_min_length: int = 3
    """Ignore clauses shorter than this (no signal in 1-2 char fragments)."""

    clause_max_length: int = 80
    """Ignore very long clauses (likely real prose, not templated)."""

    layer_a_only: bool = False
    """When True, only Layer A (n-gram suffix repetition) runs.

    Used for reasoning / thinking content where Layer B's clause-skeleton
    similarity produces too many false positives on normal structured
    reasoning (lists, confirmation steps, etc.).  Layer A still catches
    true repetition loops like "好的好的好的" in thinking streams.

    Note: Layer C (paragraph fingerprint) still runs even when
    ``layer_a_only`` is True, because large-block repetition is just as
    pathological in reasoning/thinking as in normal content.
    """

    # Layer C — paragraph fingerprint repetition (large-block loops)
    paragraph_min_length: int = 100
    """Minimum character length for a paragraph to be considered for
    fingerprinting.  Paragraphs shorter than this are ignored — they
    don't carry enough signal and cause false positives on short
    transitional lines like "……" or "好的，我来写"."""

    paragraph_window: int = 30
    """How many recent paragraphs to inspect for repetition.
    30 is large enough to span several repetitions of a multi-paragraph
    block (e.g. a 3-paragraph scene repeated 10 times = 30 paragraphs)."""

    max_paragraph_repeats: int = 3
    """How many times the same paragraph fingerprint must appear in the
    window before flagging a loop.  3 is aggressive but appropriate —
    in normal prose the same paragraph almost never appears verbatim 3+
    times.  For fuzzy matching, this also applies."""

    paragraph_similarity_threshold: float = 0.7
    """Dice coefficient threshold for two paragraphs to be considered
    structurally similar (fuzzy match).  0.7 is stricter than Layer B's
    0.6 because paragraphs carry more unique structure than clauses.
    Only used when the exact MD5 match fails."""

    paragraph_fuzzy_check: bool = True
    """When True, after checking for exact MD5 matches, also check for
    fuzzy similarity between paragraphs using character-set Dice.
    This catches near-duplicate paragraphs where the LLM makes minor
    edits (e.g. changing one word) while still being in a loop."""

    paragraph_tail_chars: int = 32000
    """Separate (larger) sliding window for Layer C paragraph analysis.

    Layer A/B use ``max_tail_chars`` (default 8000) which is too small
    for paragraph-level detection — a single novel paragraph can be
    500–1000 chars, and we need enough room for ``paragraph_window``
    (default 30) paragraphs.  32000 chars comfortably holds 30+ paragraphs
    of 1000 chars each.

    This buffer is maintained independently from the Layer A/B tail so
    that increasing it does not slow down the n-gram scan (which is
    O(tail_size * ngram_count))."""

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
        self._paragraph_tail: deque[str] = deque(maxlen=self.config.paragraph_tail_chars)
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
        self._paragraph_tail.extend(chunk)
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
        if not self.config.layer_a_only:
            result = self._check_clause_repetition(tail)
            if result.detected:
                return result

        # Layer C — paragraph fingerprint repetition (always runs,
        # even when layer_a_only is True, because large-block repetition
        # is pathological in all output types)
        result = self._check_paragraph_repetition(tail)
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
            # Skip suffixes where whitespace makes up more than 50% — mixed
            # whitespace/non-whitespace patterns like '\n    * ' are not loops.
            if sum(1 for c in suffix if c.isspace()) > len(suffix) / 2:
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

    # ------------------------------------------------------------------
    # Layer C — paragraph fingerprint repetition
    # ------------------------------------------------------------------

    def _check_paragraph_repetition(self, _tail_unused: str) -> LoopDetectionResult:
        """Detect large-block / paragraph-level repetition.

        This catches the case where an LLM outputs the same paragraph
        (or near-duplicate paragraph) multiple times.  Each "paragraph"
        is typically hundreds to thousands of characters — far larger
        than the clauses inspected by Layer B.

        Uses the separate ``_paragraph_tail`` buffer (default 32 000 chars)
        instead of the Layer A/B tail (default 8 000 chars) so that enough
        paragraphs fit in the window for reliable detection.

        Two matching strategies are used:

        1. **Exact match** — MD5 fingerprint of the normalized paragraph
           text.  Catches verbatim repetition.

        2. **Fuzzy match** (optional) — character-set Dice similarity
           between paragraphs.  Catches near-duplicates where the LLM
           makes minor edits (e.g. changing one word per repetition).

        When the same fingerprint (exact or fuzzy) appears
        ``max_paragraph_repeats`` times in the last ``paragraph_window``
        paragraphs, a loop is declared.
        """
        paragraph_text = "".join(self._paragraph_tail)
        if not paragraph_text:
            return LoopDetectionResult()

        paragraphs = _split_paragraphs(
            paragraph_text,
            min_length=self.config.paragraph_min_length,
        )
        if len(paragraphs) < self.config.max_paragraph_repeats:
            return LoopDetectionResult()

        window = paragraphs[-self.config.paragraph_window:]
        if len(window) < self.config.max_paragraph_repeats:
            return LoopDetectionResult()

        # --- Exact match check ---
        fingerprints = [_paragraph_fingerprint(p) for p in window]
        latest_fp = fingerprints[-1]
        exact_count = sum(1 for fp in fingerprints if fp == latest_fp)
        if exact_count >= self.config.max_paragraph_repeats:
            preview = _shorten_for_log(window[-1])
            return LoopDetectionResult(
                detected=True,
                reason=f"paragraph fingerprint {latest_fp[:8]} repeated {exact_count} times in last {len(window)} paragraphs (exact match)",
                layer="paragraph",
                pattern=preview,
                repeat_count=exact_count,
            )

        # --- Fuzzy match check ---
        if self.config.paragraph_fuzzy_check:
            latest_chars = frozenset(window[-1])
            if len(latest_chars) >= 10:
                threshold = self.config.paragraph_similarity_threshold
                fuzzy_count = 1
                for prev in window[:-1]:
                    prev_chars = frozenset(prev)
                    if len(prev_chars) < 10:
                        continue
                    sim = _dice(latest_chars, prev_chars)
                    if sim >= threshold:
                        fuzzy_count += 1
                if fuzzy_count >= self.config.max_paragraph_repeats:
                    preview = _shorten_for_log(window[-1])
                    return LoopDetectionResult(
                        detected=True,
                        reason=f"paragraph repeated {fuzzy_count} times in last {len(window)} paragraphs (fuzzy Dice ≥ {threshold})",
                        layer="paragraph",
                        pattern=preview,
                        repeat_count=fuzzy_count,
                    )

        return LoopDetectionResult()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PARAGRAPH_SPLIT_RE = re.compile(
    r"(?:\n\s*\n|"           # blank line
    r"\u2026\u2026|"         # ……
    r"\u2014\u2014|"         # ——
    r"\*\*\*)"               # ***
)


def _split_paragraphs(text: str, min_length: int = 100) -> list[str]:
    """Split *text* into paragraphs and return those ≥ *min_length*.

    Paragraph boundaries are: blank lines, "……", "——", and "***".
    These are common narrative separators in Chinese fiction and
    structured text.  Short fragments (< *min_length*) are discarded
    because they are typically transitional lines ("好的", "……") that
    don't carry enough signal for fingerprinting.
    """
    parts = _PARAGRAPH_SPLIT_RE.split(text)
    return [p.strip() for p in parts if len(p.strip()) >= min_length]


def _paragraph_fingerprint(text: str) -> str:
    """Return an MD5 hex digest of *text* for exact paragraph matching.

    The text is stripped of leading/trailing whitespace and normalised
    to a single-space form before hashing to avoid trivial mismatches
    due to whitespace differences.
    """
    normalised = re.sub(r"\s+", " ", text.strip())
    return hashlib.md5(normalised.encode("utf-8")).hexdigest()


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
