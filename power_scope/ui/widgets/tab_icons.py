"""tab_icons.py — 侧边导航矢量图标（QPainter 现场绘制，无位图资源）。

为什么不用 Unicode 字形 / PNG：
  - 字形（✦ U+2726、⚙ U+2699、⌁ U+2301）在 Microsoft YaHei 中普遍缺字，
    回退字体后字宽不一致 → 8 个 tab 的文字起点对不齐；
  - PNG 需要为每套主题 × 每个状态各存一份，且高分屏会发虚；
  - QPainter 矢量绘制：颜色取当前主题令牌，天然跟随主题切换，任意 DPI 清晰。

坐标系统一使用 24×24 viewBox，画笔 1.7px、圆头圆角、仅描边不填充。
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen


def _pen(p: QPainter, color, width: float = 1.7) -> None:
    pen = QPen(color if isinstance(color, QColor) else QColor(color))
    pen.setWidthF(width)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)


def _line(p: QPainter, pts) -> None:
    path = QPainterPath(QPointF(*pts[0]))
    for pt in pts[1:]:
        path.lineTo(QPointF(*pt))
    p.drawPath(path)


def _rrect(p: QPainter, x, y, w, h, r=2.0) -> None:
    p.drawRoundedRect(QRectF(x, y, w, h), r, r)


# ═══════════════════════════════════════════════════════════════
# 各图标绘制函数 — 全部在 24×24 内作图
# ═══════════════════════════════════════════════════════════════

def icon_dashboard(p: QPainter) -> None:
    """仪表盘 — 2×2 宫格。"""
    _rrect(p, 3.5, 3.5, 8, 8, 1.8)
    _rrect(p, 12.5, 3.5, 8, 8, 1.8)
    _rrect(p, 3.5, 12.5, 8, 8, 1.8)
    _rrect(p, 12.5, 12.5, 8, 8, 1.8)


def icon_wave(p: QPainter) -> None:
    """波形 — 正弦线。"""
    pts = []
    for i in range(49):
        x = 3.0 + i * (18.0 / 48.0)
        y = 12.0 + 7.0 * _sin(i * 3.14159265 * 2 / 16.0)
        pts.append((x, y))
    _line(p, pts)


def icon_serial(p: QPainter) -> None:
    """串口 — 上下双箭头（收发）。"""
    _line(p, [(12, 3.5), (12, 20.5)])
    _line(p, [(8, 7), (12, 3), (16, 7)])
    _line(p, [(8, 17), (12, 21), (16, 17)])


def icon_tree(p: QPainter) -> None:
    """变量树 — 节点 + 分支。"""
    _rrect(p, 9.5, 3.5, 5, 4, 1.2)
    _line(p, [(12, 7.5), (12, 11)])
    _line(p, [(6, 11), (18, 11)])
    _line(p, [(6, 11), (6, 14)])
    _line(p, [(18, 11), (18, 14)])
    _rrect(p, 3, 14, 6, 4, 1.2)
    _rrect(p, 15, 14, 6, 4, 1.2)


def icon_tuning(p: QPainter) -> None:
    """调参 — 三档滑杆。"""
    for y, kx in ((6.0, 15.0), (12.0, 8.5), (18.0, 17.5)):
        _line(p, [(3.5, y), (20.5, y)])
        p.setBrush(p.pen().color())
        p.drawEllipse(QRectF(kx - 2.4, y - 2.4, 4.8, 4.8))
        p.setBrush(Qt.NoBrush)


def icon_ai(p: QPainter) -> None:
    """AI — 四角星。"""
    path = QPainterPath(QPointF(12, 3.0))
    path.cubicTo(QPointF(13.2, 9.6), QPointF(14.4, 10.8), QPointF(21, 12))
    path.cubicTo(QPointF(14.4, 13.2), QPointF(13.2, 14.4), QPointF(12, 21))
    path.cubicTo(QPointF(10.8, 14.4), QPointF(9.6, 13.2), QPointF(3, 12))
    path.cubicTo(QPointF(9.6, 10.8), QPointF(10.8, 9.6), QPointF(12, 3.0))
    p.drawPath(path)


def icon_terminal(p: QPainter) -> None:
    """MSG 命令 — 终端提示符。"""
    _rrect(p, 3.0, 4.5, 18, 15, 2.2)
    _line(p, [(7, 10), (10.5, 12.8), (7, 15.6)])
    _line(p, [(13.5, 16), (17.5, 16)])


def icon_upgrade(p: QPainter) -> None:
    """串口升级 — 托盘 + 上箭头。"""
    _line(p, [(3.5, 20.5), (20.5, 20.5)])
    _line(p, [(6, 20.5), (6, 16.5), (18, 16.5), (18, 20.5)])
    _line(p, [(12, 15.5), (12, 4.5)])
    _line(p, [(7.5, 9), (12, 4.2), (16.5, 9)])


def icon_bell(p: QPainter) -> None:
    """告警 — 铃铛。"""
    path = QPainterPath(QPointF(6.5, 17.5))
    path.cubicTo(QPointF(7.5, 10.5), QPointF(9.5, 8.5), QPointF(10.5, 8.5))
    path.cubicTo(QPointF(11.5, 8.5), QPointF(13.5, 10.5), QPointF(14.5, 17.5))
    p.drawPath(path)
    _line(p, [(4.5, 17.5), (16.5, 17.5)])
    _line(p, [(10.5, 7.5), (10.5, 5.0)])
    p.drawArc(QRectF(7.6, 2.4, 5.8, 4.0), 0, 180 * 16)
    _line(p, [(10.5, 20.5), (10.5, 21.2)])


# ═══════════════════════════════════════════════════════════════════
# 工具栏按钮图标（P0-6 工具栏图标化）— 同样 24×24 stroke-only 风格
# ═══════════════════════════════════════════════════════════════════

def icon_connect(p: QPainter) -> None:
    """连接 — 插头。"""
    _line(p, [(4, 8), (4, 16)])
    _line(p, [(8, 9.5), (8, 14.5)])
    _line(p, [(8, 12), (15, 12)])
    _line(p, [(15, 8), (15, 16)])
    _line(p, [(18.5, 9.5), (18.5, 14.5)])
    _line(p, [(20.5, 10.5), (20.5, 13.5)])


def icon_swap(p: QPainter) -> None:
    """切换设备 — 双向对调箭头。"""
    _line(p, [(4, 9), (20, 9)])
    _line(p, [(16, 5.5), (20, 9), (16, 12.5)])
    _line(p, [(20, 15), (4, 15)])
    _line(p, [(8, 11.5), (4, 15), (8, 18.5)])


def icon_palette(p: QPainter) -> None:
    """主题 — 调色板。"""
    p.drawArc(QRectF(3.5, 3.5, 17, 17), 0, 300 * 16)
    p.setBrush(p.pen().color())
    p.drawEllipse(QRectF(6, 6.5, 2.6, 2.6))
    p.drawEllipse(QRectF(11, 5.5, 2.6, 2.6))
    p.drawEllipse(QRectF(15, 8.5, 2.6, 2.6))
    p.drawEllipse(QRectF(4, 13, 2.6, 2.6))
    p.setBrush(Qt.NoBrush)


def icon_search(p: QPainter) -> None:
    """命令面板 — 放大镜。"""
    p.drawEllipse(QRectF(4.0, 4.0, 11.5, 11.5))
    _line(p, [(13.4, 13.4), (19.5, 19.5)])


def icon_send(p: QPainter) -> None:
    """发送 — 纸飞机。"""
    path = QPainterPath(QPointF(3.5, 11.5))
    path.lineTo(QPointF(20.5, 4.0))
    path.lineTo(QPointF(13.5, 20.5))
    path.lineTo(QPointF(10.8, 13.6))
    path.closeSubpath()
    p.drawPath(path)
    _line(p, [(10.8, 13.6), (20.5, 4.0)])


def icon_plus(p: QPainter) -> None:
    """添加 — 加号。"""
    _line(p, [(12, 4.5), (12, 19.5)])
    _line(p, [(4.5, 12), (19.5, 12)])


def icon_minus(p: QPainter) -> None:
    """移除 — 减号。"""
    _line(p, [(4.5, 12), (19.5, 12)])


def icon_export(p: QPainter) -> None:
    """导出 — 托盘 + 下箭头。"""
    _line(p, [(4, 20.5), (20, 20.5)])
    _line(p, [(6.5, 20.5), (6.5, 16.5), (17.5, 16.5), (17.5, 20.5)])
    _line(p, [(12, 4.5), (12, 14.5)])
    _line(p, [(7.5, 10), (12, 14.5), (16.5, 10)])


def icon_record(p: QPainter) -> None:
    """录波 — 实心圆点 + 外圈。"""
    p.setBrush(p.pen().color())
    p.drawEllipse(QRectF(8, 8, 8, 8))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QRectF(3.5, 3.5, 17, 17))


def icon_trigger(p: QPainter) -> None:
    """触发 — 闪电。"""
    path = QPainterPath(QPointF(13.5, 3.5))
    path.lineTo(QPointF(6.5, 13))
    path.lineTo(QPointF(11, 13))
    path.lineTo(QPointF(10, 20.5))
    path.lineTo(QPointF(17.5, 10.5))
    path.lineTo(QPointF(13, 10.5))
    path.closeSubpath()
    p.drawPath(path)


def icon_file(p: QPainter) -> None:
    """文件 — 折角文档。"""
    _line(p, [(6, 3.5), (14.5, 3.5), (18, 7), (18, 20.5), (6, 20.5), (6, 3.5)])
    _line(p, [(14.5, 3.5), (14.5, 7), (18, 7)])


def icon_report(p: QPainter) -> None:
    """调试报告 — 文档 + 折线。"""
    _rrect(p, 4.5, 3.5, 15, 17, 1.8)
    _line(p, [(8, 14.5), (10.5, 11.5), (12.5, 13), (16, 9)])


def icon_replay(p: QPainter) -> None:
    """回放 — 时钟 + 指针。"""
    p.drawEllipse(QRectF(3.5, 4.5, 17, 17))
    _line(p, [(12, 7.5), (12, 12.5), (16, 15)])


def icon_save(p: QPainter) -> None:
    """保存 — 软盘。"""
    _rrect(p, 4.5, 3.5, 15, 17, 1.8)
    _line(p, [(8, 3.5), (8, 9), (16, 9), (16, 3.5)])
    _rrect(p, 8.5, 12.5, 7, 5, 1.0)


def icon_edit(p: QPainter) -> None:
    """编辑 — 铅笔。"""
    _line(p, [(4.5, 19.5), (6.5, 15), (15.5, 6), (18, 8.5), (9, 18)])
    _line(p, [(15.5, 6), (17.5, 4), (20, 6.5), (18, 8.5)])


def icon_refresh(p: QPainter) -> None:
    """刷新 — 环形箭头。"""
    p.drawArc(QRectF(4.5, 4.5, 15, 15), 40 * 16, 280 * 16)
    _line(p, [(17.5, 6.5), (19.5, 10.5), (15.5, 11.5)])


def icon_play(p: QPainter) -> None:
    """播放 — 三角。"""
    path = QPainterPath(QPointF(7, 4.5))
    path.lineTo(QPointF(19, 12))
    path.lineTo(QPointF(7, 19.5))
    path.closeSubpath()
    p.drawPath(path)


def icon_pause(p: QPainter) -> None:
    """暂停 — 双竖条。"""
    _line(p, [(8.5, 5), (8.5, 19)])
    _line(p, [(15.5, 5), (15.5, 19)])


def icon_clear(p: QPainter) -> None:
    """清空 — 扫帚/垃圾桶简化形。"""
    _line(p, [(4, 6.5), (20, 6.5)])
    _line(p, [(6, 6.5), (7.5, 20.5)])
    _line(p, [(18, 6.5), (16.5, 20.5)])
    _line(p, [(7.5, 20.5), (16.5, 20.5)])
    _line(p, [(10, 3.5), (10, 6.5)])
    _line(p, [(14, 3.5), (14, 6.5)])


_ICONS = {
    "dashboard": icon_dashboard,
    "wave": icon_wave,
    "serial": icon_serial,
    "tree": icon_tree,
    "tuning": icon_tuning,
    "ai": icon_ai,
    "terminal": icon_terminal,
    "upgrade": icon_upgrade,
    "bell": icon_bell,
    # 工具栏/按钮图标
    "connect": icon_connect,
    "swap": icon_swap,
    "palette": icon_palette,
    "search": icon_search,
    "send": icon_send,
    "plus": icon_plus,
    "minus": icon_minus,
    "export": icon_export,
    "record": icon_record,
    "trigger": icon_trigger,
    "file": icon_file,
    "report": icon_report,
    "replay": icon_replay,
    "save": icon_save,
    "edit": icon_edit,
    "refresh": icon_refresh,
    "play": icon_play,
    "pause": icon_pause,
    "clear": icon_clear,
}


def _sin(x: float) -> float:
    """本地 sin（避免 import math 的开销，绘制频率极低）。"""
    x = x % 6.283185307
    if x > 3.141592654:
        x -= 6.283185307
    x2 = x * x
    return x * (1 - x2 / 6.0 * (1 - x2 / 20.0 * (1 - x2 / 42.0)))


def available() -> list:
    """已注册图标名列表。"""
    return sorted(_ICONS)


def draw_icon(painter: QPainter, name: str, rect, color: str) -> bool:
    """在 rect 内居中绘制名为 name 的图标；未注册返回 False。"""
    fn = _ICONS.get(name)
    if fn is None:
        return False
    side = min(rect.width(), rect.height())
    box = QRectF(rect.x() + (rect.width() - side) / 2.0,
                 rect.y() + (rect.height() - side) / 2.0, side, side)
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)
    # 24×24 viewBox → 实际像素
    painter.translate(box.x(), box.y())
    painter.scale(side / 24.0, side / 24.0)
    _pen(painter, color)
    painter.setBrush(Qt.NoBrush)
    fn(painter)
    painter.restore()
    return True
