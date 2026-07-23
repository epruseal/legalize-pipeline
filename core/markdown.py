"""Markdown text helpers shared by data converters."""

from __future__ import annotations

import re


_MARKDOWN_LINK_RE = re.compile(
    r"""(?<!!)(?<!\\)\[(?P<label>[^\]\n]+)\]\((?P<target>[^)\n]+)\)"""
)
_URL_PREFIXES = ("http://", "https://", "mailto:", "tel:")


def escape_accidental_markdown_links(text: str) -> str:
    """Escape source text that accidentally looks like a relative Markdown link.

    Legal source text often uses forms such as ``[별표 3](일반직등)`` as plain
    prose. Markdown would render those as broken relative links, so keep the
    visible text while neutralizing only non-URL link targets.
    """

    def replace(match: re.Match[str]) -> str:
        target = match.group("target").strip()
        if target.startswith(_URL_PREFIXES) or target.startswith("#"):
            return match.group(0)
        return f"\\[{match.group('label')}]({match.group('target')})"

    return _MARKDOWN_LINK_RE.sub(replace, text)
