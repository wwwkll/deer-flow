# -*- coding: utf-8 -*-
import logging
import re
import time
from pathlib import Path

from langchain.tools import tool

from my_tools.path_resolver import resolve_to_host_path

logger = logging.getLogger(__name__)

_PUNCTUATION_PATTERN = re.compile(
    r'[，。！？、；：\u201c\u201d\u2018\u2019【】《》（）…—·\-\+\=\*\&\^\%\$\#\@\!\~\`\[\]\{\}\|\\\:;\"\'<>\?\,\.\!\/\(\)]+'
)

_CJK_PUNCTUATION = set(
    '，。！？、；：\u201c\u201d\u2018\u2019【】《》（）…—·'
    '～〃〆〇〈〉〔〕〖〗〘〙〚〛'
)

_MD_SYNTAX_PATTERN = re.compile(r'^#{1,6}\s+|^\s*[-*+]\s+|^\s*\d+\.\s+|^\s*>\s+')

_MARKDOWN_LINK_IMG = re.compile(r'!\[.*?\]\(.*?\)|\[.*?\]\(.*?\)')

_MARKDOWN_CODE = re.compile(r'```[\s\S]*?```|`[^`]+`')

_MARKDOWN_HTML = re.compile(r'<[^>]+>')

_MARKDOWN_HR = re.compile(r'^---+$|^\*\*\*+$|^___+$', re.MULTILINE)


def _resolve_path(file_path: str) -> str:
    normalized = file_path.replace("\\", "/").strip()
    if normalized.startswith("/"):
        return resolve_to_host_path(normalized)
    relative = normalized.removeprefix("./")
    return resolve_to_host_path(f"/mnt/shared-data/{relative}")


def _is_within_shared_data(file_path: str) -> bool:
    shared_data = resolve_to_host_path("/mnt/shared-data").replace("\\", "/")
    target = str(Path(file_path.replace("\\", "/")).resolve()).replace("\\", "/")
    return target.startswith(shared_data)


def _strip_markdown_syntax(text: str) -> str:
    text = _MARKDOWN_CODE.sub('', text)
    text = _MARKDOWN_LINK_IMG.sub('', text)
    text = _MARKDOWN_HTML.sub('', text)
    text = _MARKDOWN_HR.sub('', text)
    lines = text.split('\n')
    cleaned = []
    for line in lines:
        line = _MD_SYNTAX_PATTERN.sub('', line)
        cleaned.append(line)
    return '\n'.join(cleaned)


def _count_words(text: str) -> dict:
    cleaned = _strip_markdown_syntax(text)

    no_punct = _PUNCTUATION_PATTERN.sub('', cleaned)
    for ch in _CJK_PUNCTUATION:
        no_punct = no_punct.replace(ch, '')

    cjk_chars = 0
    en_letters = 0
    digit_chars = 0

    for ch in no_punct:
        if '\u4e00' <= ch <= '\u9fff' or '\u3400' <= ch <= '\u4dbf' or '\uf900' <= ch <= '\ufaff':
            cjk_chars += 1
        elif ch.isdigit():
            digit_chars += 1
        elif ch.isalpha():
            en_letters += 1

    total = cjk_chars + en_letters + digit_chars
    return {
        'total': total,
        'cjk_chars': cjk_chars,
        'en_letters': en_letters,
        'digit_chars': digit_chars,
    }


@tool("word_counter", parse_docstring=True)
def word_counter(
    description: str,
    file_path: str,
) -> str:
    """统计 .md 文件的字数（不含标点符号）。

    读取 Markdown 文件并统计总字数，自动排除标点符号和 Markdown 语法标记。
    统计规则：每个非标点字符算1字（汉字、英文字母、数字各算1字）。
    排除项：中英文标点符号、Markdown 标题/列表/链接/代码块/图片等语法标记。

    Args:
        description: 操作说明，简短描述为什么执行此操作。ALWAYS PROVIDE THIS PARAMETER FIRST.
        file_path: 目标文件路径（绝对路径如 /mnt/shared-data/...，或相对路径如 book/小说名/02-正文/第1章.md）
    """
    start_time = time.time()
    host_path = _resolve_path(file_path)
    logger.info("[word_counter] input=%s, host_path=%s", file_path, host_path)

    if not _is_within_shared_data(host_path):
        elapsed = time.time() - start_time
        logger.warning("[word_counter] path out of range: %s | elapsed=%.3fs", host_path, elapsed)
        return f"[FAIL] 权限拒绝：路径超出允许范围：{file_path}"

    target = Path(host_path)
    if not target.exists():
        elapsed = time.time() - start_time
        logger.warning("[word_counter] file not found: %s | elapsed=%.3fs", host_path, elapsed)
        return f"[FAIL] 文件不存在：{file_path}"

    if not target.is_file():
        elapsed = time.time() - start_time
        logger.warning("[word_counter] path is directory: %s | elapsed=%.3fs", host_path, elapsed)
        return f"[FAIL] 路径是目录，不是文件：{file_path}"

    if not host_path.lower().endswith('.md'):
        elapsed = time.time() - start_time
        logger.warning("[word_counter] not a .md file: %s | elapsed=%.3fs", host_path, elapsed)
        return f"[FAIL] 仅支持 .md 文件，当前文件：{file_path}"

    try:
        content = target.read_text(encoding='utf-8')
    except UnicodeDecodeError as e:
        elapsed = time.time() - start_time
        logger.error("[word_counter] encoding error: %s | elapsed=%.3fs", e, elapsed)
        return f"[FAIL] 文件编码错误：{str(e)}"
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error("[word_counter] read error: %s | elapsed=%.3fs", e, elapsed)
        return f"[FAIL] 读取文件失败：{str(e)}"

    result = _count_words(content)
    elapsed = time.time() - start_time

    logger.info(
        "[word_counter] success: file=%s, total=%d, cjk=%d, en_letters=%d, digits=%d | elapsed=%.3fs",
        file_path, result['total'], result['cjk_chars'], result['en_letters'], result['digit_chars'], elapsed,
    )

    return (
        f"[OK] 字数统计完成（不含标点符号）\n"
        f"文件：{file_path}\n"
        f"总字数：{result['total']}（不含标点符号）\n"
        f"  - 中文字符：{result['cjk_chars']}\n"
        f"  - 英文字母：{result['en_letters']}\n"
        f"  - 数字字符：{result['digit_chars']}"
    )
