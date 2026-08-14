"""敏感信息检测：正则识别文档中的个人/机密信息，用于合规告警。

标签: id_card(身份证) / phone(手机号) / bank_card(银行卡) / email(邮箱) / ip(IP地址) / api_key(API密钥)
"""
from __future__ import annotations

import re
from typing import List

_PATTERNS: list[tuple[str, str, re.Pattern]] = [
    # (标签, 中文名, 正则)
    ("id_card", "身份证号", re.compile(r"\b\d{17}[\dXx]\b")),
    ("phone", "手机号", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    ("bank_card", "银行卡号", re.compile(r"(?<!\d)\d{16,19}(?!\d)")),
    ("email", "邮箱", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("ip", "IP地址", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    ("api_key", "API密钥", re.compile(r"\bsk-[A-Za-z0-9]{16,}\b")),
]

FLAG_NAMES = {tag: name for tag, name, _ in _PATTERNS}


def detect_sensitive(text: str) -> List[str]:
    """检测文本中的敏感信息，返回命中的标签列表（去重、保序）。"""
    hits: List[str] = []
    for tag, _name, pattern in _PATTERNS:
        if pattern.search(text) and tag not in hits:
            hits.append(tag)
    return hits


def detect_sensitive_join(text: str) -> str:
    """检测并返回逗号分隔的标签串（存库格式）。"""
    return ",".join(detect_sensitive(text))


# ---------- 脱敏掩码（用于 AI 回答的合规展示） ----------
_MASKERS: list[tuple[str, re.Pattern, str]] = [
    # (标签, 正则, 替换模板)
    ("phone", re.compile(r"(?<!\d)(1[3-9]\d)\d{4}(\d{4})(?!\d)"), r"\1****\2"),
    ("id_card", re.compile(r"\b(\d{4})\d{9}(\d{4}[\dXx])\b"), r"\1*********\2"),
    ("bank_card", re.compile(r"(?<!\d)(\d{4})\d{8,11}(\d{4})(?!\d)"), r"\1********\2"),
    ("email", re.compile(r"([\w.+-]{1,3})[\w.+-]*@([\w-]+\.[\w.-]+)"), r"\1***@\2"),
    ("ip", re.compile(r"(\d{1,3})\.\d{1,3}\.\d{1,3}\.\d{1,3}"), r"\1.***.***.***"),
    ("api_key", re.compile(r"\bsk-[A-Za-z0-9]{16,}\b"), "sk-***"),
]


def mask_text(text: str) -> str:
    """对文本中的敏感信息打码（身份证/手机号/银行卡/邮箱/IP/API密钥）。"""
    if not text:
        return text
    masked = text
    for _tag, pattern, repl in _MASKERS:
        masked = pattern.sub(repl, masked)
    return masked
