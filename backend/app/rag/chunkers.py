"""文本切分器。

策略（按文档类型）：
- Markdown：按标题层级切分为语义块，再做长度控制（子块合并/拆分）
- 其他文本：按空行分段（段落即语义单元，如简历的项目/经历条目），再做长度控制
- 超长段内部定长切分 + 重叠
每个 chunk 返回 {text, metadata:{...}}
"""
from __future__ import annotations

import re
from typing import List

from app.core.config import settings

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")


def _split_by_heading(text: str) -> List[str]:
    """按 Markdown 标题切成段落块，保留标题行。"""
    lines = text.split("\n")
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if HEADING_RE.match(line.strip()):
            if current:
                blocks.append(current)
            current = [line]
        else:
            current.append(line)
    if current:
        blocks.append(current)
    return ["\n".join(b).strip() for b in blocks if "\n".join(b).strip()]


def _split_by_blank_line(text: str) -> List[str]:
    """按空行分段：段落是天然语义单元（简历项目、制度条款等），保持段落完整。"""
    parts = re.split(r"\n\s*\n", text)
    return [p.strip() for p in parts if p.strip()]


def _merge_blocks(blocks: List[str], size: int, overlap: int) -> List[str]:
    """合并小块到 size 附近；超过 size 的块内部再切分。"""
    out: List[str] = []
    buffer = ""
    for b in blocks:
        if len(b) >= size:
            if buffer:
                out.append(buffer)
                buffer = ""
            out.extend(_fixed_chunk(b, size, overlap))
            continue
        if buffer and len(buffer) + 1 + len(b) > size * 1.6:
            out.append(buffer)
            buffer = b
        else:
            buffer = (buffer + "\n\n" + b) if buffer else b
    if buffer:
        out.append(buffer)
    return out


def _fixed_chunk(text: str, size: int, overlap: int) -> List[str]:
    """定长切分 + 重叠（在换行边界回退）。"""
    if len(text) <= size:
        return [text.strip()] if text.strip() else []
    chunks: List[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            cut = text.rfind("\n", start + int(size * 0.6), end)
            if cut > start:
                end = cut
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def chunk_document(
    text: str,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    is_markdown: bool = False,
) -> List[dict]:
    """文档级切分，返回 [{"text": str, "metadata": {"section": str|None}}]。"""
    size = chunk_size or settings.CHUNK_SIZE
    overlap = chunk_overlap or settings.CHUNK_OVERLAP
    overlap = min(overlap, size // 2)
    if not text.strip():
        return []

    if is_markdown:
        blocks = _split_by_heading(text)
        merged = _merge_blocks(blocks, size, overlap)
    else:
        blocks = _split_by_blank_line(text)
        merged = _merge_blocks(blocks, size, overlap)

    out: List[dict] = []
    for m in merged:
        if not m.strip():
            continue
        section = None
        first = m.strip().split("\n", 1)[0]
        hm = HEADING_RE.match(first)
        if hm:
            section = hm.group(2).strip()
        out.append({"text": m.strip(), "metadata": {"section": section}})
    return out
