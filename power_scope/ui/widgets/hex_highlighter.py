"""hex_highlighter.py — Hex 帧语法高亮（P1-9 发送增强）

多行序列发送前逐行着色，让「哪一帧写错了」在发送前就可见：
  - 合法 Hex 字节（两位十六进制）   → 主文字色
  - 字节数非整 / 含非 Hex 字符      → 错误红
  - 空行 / 注释行（# 开头）          → 暗色
颜色全部走主题令牌，不写死 hex。
"""
from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat

from ..theme import ui_color

_BYTE_RE = re.compile(r"\b[0-9A-Fa-f]{2}\b")
_HEXISH_RE = re.compile(r"^[0-9A-Fa-f\s]*$")


class HexHighlighter(QSyntaxHighlighter):
    """按行着色：好行=主文字色，坏行=错误红，注释/空行=暗色。"""

    def __init__(self, document):
        super().__init__(document)
        self._fmt_ok = QTextCharFormat()
        self._fmt_err = QTextCharFormat()
        self._fmt_dim = QTextCharFormat()

    def apply_theme(self, theme_name=None):
        """主题切换后重新解析语义色并整篇重着色。"""
        self._fmt_ok.setForeground(QColor(ui_color("text")))
        self._fmt_ok.setFont(QFont("Cascadia Code, Consolas, monospace"))
        self._fmt_err.setForeground(QColor(ui_color("danger")))
        self._fmt_dim.setForeground(QColor(ui_color("text_dim")))
        self.rehighlight()
        del theme_name

    def highlightBlock(self, text: str):
        if not text.strip() or text.strip().startswith("#"):
            self.setFormat(0, len(text), self._fmt_dim)
            return
        clean = text.replace(",", " ").replace(";", " ").strip()
        if not _HEXISH_RE.match(clean) or len(clean.replace(" ", "")) % 2 != 0:
            self.setFormat(0, len(text), self._fmt_err)
            return
        # 逐字节着色：合法字节 → 主色；不在字节里的非空白字符 → 错误色
        covered = [False] * len(text)
        for match in _BYTE_RE.finditer(text):
            self.setFormat(match.start(), match.end(), self._fmt_ok)
            for i in range(match.start(), match.end()):
                covered[i] = True
        for i, ch in enumerate(text):
            if not covered[i] and not ch.isspace():
                self.setFormat(i, 1, self._fmt_err)


def parse_hex_lines(text: str) -> tuple[list[str], list[str]]:
    """把多行序列文本解析成 (合法帧列表, 错误行列表)。

    每行一帧；'#' 开头为注释，空行忽略。返回错误行原文供提示。
    """
    frames: list[str] = []
    errors: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        clean = line.replace(",", " ").replace(";", " ")
        tokens = clean.split()
        hex_body = "".join(tokens)
        if not _HEXISH_RE.match(hex_body) or len(hex_body) % 2 != 0:
            errors.append(line)
            continue
        frames.append(hex_body)
    return frames, errors
