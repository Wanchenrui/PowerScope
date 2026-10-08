"""command_index.py — 全局命令面板的索引与模糊搜索（P0-4 的纯逻辑层）

Ctrl+K 命令面板的一切计算都在这里完成：条目模型、模糊打分、分组排序。
不 import Qt —— 可独立单测；command_palette.py 只负责呈现与派发。

条目类型（kind）：
  page     页签直达（payload=tab 索引）
  variable profile 变量（payload=变量名）
  symbol   ELF 符号（payload=符号名）
  msg      MSG 命令字（payload=0x 命令字）
  action   应用动作（payload=动作 key，由调用方注册回调执行）
"""
from __future__ import annotations

from dataclasses import dataclass, field

#: 分组展示顺序（未列出的 kind 排在最后）
_KIND_ORDER = ("action", "page", "variable", "symbol", "msg")

_KIND_LABELS = {
    "action": "动作",
    "page": "页签",
    "variable": "变量",
    "symbol": "符号",
    "msg": "MSG",
}


@dataclass(frozen=True)
class CommandItem:
    """一条可直达的索引条目。"""

    kind: str
    title: str
    subtitle: str = ""
    payload: object = None
    keywords: tuple[str, ...] = field(default_factory=tuple)

    def search_text(self) -> str:
        parts = [self.title, self.subtitle, *self.keywords]
        return " ".join(p for p in parts if p).lower()


def fuzzy_score(query: str, text: str) -> int:
    """子序列模糊匹配打分（0 = 不匹配）。

    规则：query 的每个字符必须按顺序出现在 text 中；
    连续命中加权，词首命中加权，命中越靠前分越高。
    """
    if not query:
        return 1
    qi = 0
    score = 0
    streak = 0
    last = -2
    for ti, ch in enumerate(text):
        if qi >= len(query):
            break
        if ch == query[qi]:
            streak = streak + 1 if ti == last + 1 else 1
            score += 10 + streak * 4
            if ti == 0 or text[ti - 1] in " _-/.":
                score += 8          # 词首命中
            score += max(0, 6 - ti // 8)
            last = ti
            qi += 1
    return score if qi >= len(query) else 0


def search(items: list[CommandItem], query: str,
           limit: int = 50) -> list[tuple[CommandItem, int]]:
    """按相关度排序返回 (item, score)；空 query 返回默认分组前 limit 条。"""
    q = (query or "").strip().lower()
    if not q:
        return [(item, 0) for item in items[:limit]]
    scored: list[tuple[CommandItem, int]] = []
    for item in items:
        score = fuzzy_score(q, item.search_text())
        if score > 0:
            scored.append((item, score))
    scored.sort(key=lambda pair: (-pair[1], _KIND_ORDER.index(pair[0].kind)
                                  if pair[0].kind in _KIND_ORDER else 99))
    return scored[:limit]


def kind_label(kind: str) -> str:
    return _KIND_LABELS.get(kind, kind)
