from __future__ import annotations

import re

TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+")
STOPWORDS = {
    "这",
    "那",
    "哪",
    "份",
    "资",
    "料",
    "有",
    "没",
    "提",
    "到",
    "的",
    "了",
    "是",
    "吗",
    "和",
    "与",
    "或",
    "在",
    "中",
    "对",
    "将",
    "可",
    "以",
    "为",
    "个",
    "一",
    "资料",
    "文档",
    "是否",
    "有没有",
    "提到",
    "介绍",
    "说明",
    "讨论",
    "这份",
    "系统",
    "哪些",
    "什么",
    "怎么",
    "如何",
}

RETRIEVAL_ALIASES = {
    "重复提交": ("幂等", "幂等键"),
    "重复投递": ("幂等", "幂等键"),
}


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in TOKEN_RE.findall(text):
        token = raw.lower()
        if token in STOPWORDS:
            continue
        if re.fullmatch(r"[\u4e00-\u9fff]+", token):
            if len(token) <= 2:
                if token not in STOPWORDS:
                    tokens.append(token)
            else:
                for start in range(0, len(token) - 1):
                    part = token[start : start + 2]
                    if part not in STOPWORDS:
                        tokens.append(part)
                if len(token) <= 6 and token not in STOPWORDS:
                    tokens.append(token)
        else:
            tokens.append(token)
    return tokens


def retrieval_tokens(text: str) -> list[str]:
    """Tokenize and add a small, auditable domain alias set for lexical recall."""

    tokens = tokenize(text)
    lowered = text.lower()
    for phrase, aliases in RETRIEVAL_ALIASES.items():
        if phrase in lowered:
            for alias in aliases:
                for token in tokenize(alias):
                    if token not in tokens:
                        tokens.append(token)
    return tokens
