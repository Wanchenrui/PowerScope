"""icons.py — 高 DPI 矢量图标库（纯 QPainter 绘制，无第三方资源依赖）

设计约定：
  - 全部图标在 24×24 网格上设计，统一线宽 1.7、圆角线帽/拐角（工业风圆润感）
  - paint_icon() 供侧边栏/按钮按主题色实时重绘（换主题不重载资源）
  - icon() 预渲染静态 QIcon（按 size 与屏幕 DPR 渲染，保证非空且高分屏不糊）
  - 未知名称回退到稳定的占位图形（圆角方块 + 圆点），不会留白或抛错
"""
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)

_GRID = 24.0   # 设计网格
_STROKE = 1.7  # 统一线宽


def _line(painter: QPainter, color: str, width: float = _STROKE) -> None:
    """统一描边：圆角线帽/拐角，默认无填充。"""
    pen = QPen(QColor(color))
    pen.setWidthF(width)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)


def _fill(painter: QPainter, color: str) -> None:
    """统一实心填充（用于圆点/播放块等）。"""
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(color))


def _poly(painter: QPainter, *pts) -> None:
    painter.drawPolyline(QPolygonF([QPointF(x, y) for x, y in pts]))


# ═══════════════════════════════════════════════════════════════════
# 图标绘制 — 每个函数在 24×24 坐标系内以 color 作画
# ═══════════════════════════════════════════════════════════════════

def _dashboard(p: QPainter, c: str) -> None:
    _line(p, c)
    for rect in ((3, 3, 8, 8), (13, 3, 8, 8), (3, 13, 8, 8), (13, 13, 8, 8)):
        p.drawRoundedRect(QRectF(*rect), 1.6, 1.6)


def _waveform(p: QPainter, c: str) -> None:
    _line(p, c)
    _poly(p, (2, 12), (6, 12), (9, 5), (12, 19), (15, 7), (18, 12), (22, 12))


def _serial(p: QPainter, c: str) -> None:
    _line(p, c)
    p.drawRoundedRect(QRectF(3.5, 8.5, 17, 7), 2, 2)
    p.drawLine(QPointF(12, 15.5), QPointF(12, 21))
    _fill(p, c)
    for x in (8, 12, 16):
        p.drawEllipse(QPointF(x, 12), 1.05, 1.05)


def _variable(p: QPainter, c: str) -> None:
    _line(p, c)
    _poly(p, (10, 4), (20, 4), (20, 20), (10, 20), (4, 12), (10, 4))
    _fill(p, c)
    p.drawEllipse(QPointF(14, 12), 1.6, 1.6)


def _tuning(p: QPainter, c: str) -> None:
    _line(p, c)
    for y in (6.5, 12, 17.5):
        p.drawLine(QPointF(3, y), QPointF(21, y))
    _fill(p, c)
    for x, y in ((15, 6.5), (8, 12), (13, 17.5)):
        p.drawEllipse(QPointF(x, y), 2.2, 2.2)


def _ai(p: QPainter, c: str) -> None:
    _line(p, c)
    _poly(p, (12, 3), (14.2, 9.8), (21, 12), (14.2, 14.2), (12, 21),
          (9.8, 14.2), (3, 12), (9.8, 9.8), (12, 3))


def _msg(p: QPainter, c: str) -> None:
    _line(p, c)
    p.drawRoundedRect(QRectF(3, 4, 18, 12), 3, 3)
    _poly(p, (8, 16), (8, 21), (13, 16))


def _upgrade(p: QPainter, c: str) -> None:
    _line(p, c)
    p.drawLine(QPointF(12, 15), QPointF(12, 4.5))
    _poly(p, (7.5, 9.5), (12, 4.5), (16.5, 9.5))
    _poly(p, (4, 15.5), (4, 19.5), (20, 19.5), (20, 15.5))


def _disconnect(p: QPainter, c: str) -> None:
    _line(p, c)
    p.drawRoundedRect(QRectF(3, 9, 9, 6), 1.5, 1.5)
    p.drawLine(QPointF(12, 10.5), QPointF(16, 10.5))
    p.drawLine(QPointF(12, 13.5), QPointF(16, 13.5))
    p.drawLine(QPointF(4, 20), QPointF(20, 4))


def _connect(p: QPainter, c: str) -> None:
    _line(p, c)
    p.drawRoundedRect(QRectF(3, 9, 10, 6), 1.5, 1.5)
    p.drawLine(QPointF(13, 10.5), QPointF(19, 10.5))
    p.drawLine(QPointF(13, 13.5), QPointF(19, 13.5))
    p.drawLine(QPointF(6, 15), QPointF(6, 19.5))


def _device(p: QPainter, c: str) -> None:
    _line(p, c)
    p.drawRoundedRect(QRectF(7, 7, 10, 10), 1.2, 1.2)
    for t in (9, 12, 15):
        p.drawLine(QPointF(t, 4), QPointF(t, 7))
        p.drawLine(QPointF(t, 17), QPointF(t, 20))
        p.drawLine(QPointF(4, t), QPointF(7, t))
        p.drawLine(QPointF(17, t), QPointF(20, t))


def _theme(p: QPainter, c: str) -> None:
    half = QPainterPath()
    half.moveTo(12, 4)
    half.arcTo(QRectF(4, 4, 16, 16), 90, 180)
    half.closeSubpath()
    _fill(p, c)
    p.drawPath(half)
    _line(p, c)
    p.drawEllipse(QPointF(12, 12), 8, 8)
    p.drawLine(QPointF(12, 4), QPointF(12, 20))


def _plus(p: QPainter, c: str) -> None:
    _line(p, c)
    _poly(p, (12, 5), (12, 19))
    _poly(p, (5, 12), (19, 12))


def _remove(p: QPainter, c: str) -> None:
    _line(p, c)
    _poly(p, (5, 12), (19, 12))


def _play(p: QPainter, c: str) -> None:
    _fill(p, c)
    p.drawPolygon(QPolygonF([QPointF(8.5, 5.5), QPointF(18.5, 12), QPointF(8.5, 18.5)]))


def _pause(p: QPainter, c: str) -> None:
    _line(p, c, 2.6)
    _poly(p, (9, 5.5), (9, 18.5))
    _poly(p, (15, 5.5), (15, 18.5))


def _stop(p: QPainter, c: str) -> None:
    _fill(p, c)
    p.drawRoundedRect(QRectF(6, 6, 12, 12), 2, 2)


def _clear(p: QPainter, c: str) -> None:
    _line(p, c)
    p.drawEllipse(QPointF(12, 12), 8, 8)
    _poly(p, (9, 9), (15, 15))
    _poly(p, (15, 9), (9, 15))


def _export(p: QPainter, c: str) -> None:
    _line(p, c)
    p.drawLine(QPointF(12, 9), QPointF(12, 19.5))
    _poly(p, (7.5, 14.5), (12, 19.5), (16.5, 14.5))
    _poly(p, (4, 8.5), (4, 4.5), (20, 4.5), (20, 8.5))


def _refresh(p: QPainter, c: str) -> None:
    _line(p, c)
    cx = cy = 12.0
    r = 7.5
    a0 = 50.0
    sweep = 265.0
    path = QPainterPath()
    path.moveTo(cx + r * math.cos(math.radians(a0)), cy - r * math.sin(math.radians(a0)))
    path.arcTo(QRectF(cx - r, cy - r, 2 * r, 2 * r), a0, sweep)
    p.drawPath(path)
    a1 = math.radians(a0 + sweep)
    tip = QPointF(cx + r * math.cos(a1), cy - r * math.sin(a1))
    dx, dy = -math.sin(a1), -math.cos(a1)  # 末端行进方向
    for spread in (28, -28):
        ra = math.radians(spread)
        rx = dx * math.cos(ra) - dy * math.sin(ra)
        ry = dx * math.sin(ra) + dy * math.cos(ra)
        p.drawLine(tip, QPointF(tip.x() - 4.4 * rx, tip.y() - 4.4 * ry))


def _send(p: QPainter, c: str) -> None:
    _line(p, c)
    p.drawPolygon(QPolygonF([QPointF(3, 11), QPointF(21, 3.5),
                             QPointF(14.5, 20.5), QPointF(11.2, 13.6)]))
    p.drawLine(QPointF(11.2, 13.6), QPointF(21, 3.5))


def _settings(p: QPainter, c: str) -> None:
    _line(p, c)
    p.drawEllipse(QPointF(12, 12), 3.2, 3.2)
    for k in range(8):
        a = math.radians(k * 45)
        p.drawLine(QPointF(12 + 5.6 * math.cos(a), 12 + 5.6 * math.sin(a)),
                   QPointF(12 + 9 * math.cos(a), 12 + 9 * math.sin(a)))


def _folder(p: QPainter, c: str) -> None:
    _line(p, c)
    p.drawRoundedRect(QRectF(3, 8, 18, 12), 2, 2)
    _poly(p, (3, 8), (3, 6.2), (9.5, 6.2), (11.3, 8))


def _warning(p: QPainter, c: str) -> None:
    _line(p, c)
    _poly(p, (12, 4), (21, 19.5), (3, 19.5), (12, 4))
    _poly(p, (12, 9.5), (12, 14.3))
    _fill(p, c)
    p.drawEllipse(QPointF(12, 17), 1.0, 1.0)


def _success(p: QPainter, c: str) -> None:
    _line(p, c)
    p.drawEllipse(QPointF(12, 12), 8, 8)
    _poly(p, (7.3, 12.4), (10.7, 15.8), (16.7, 8.2))


def _info(p: QPainter, c: str) -> None:
    _line(p, c)
    p.drawEllipse(QPointF(12, 12), 8, 8)
    _poly(p, (12, 11), (12, 16.3))
    _fill(p, c)
    p.drawEllipse(QPointF(12, 8), 1.0, 1.0)


def _clock(p: QPainter, c: str) -> None:
    _line(p, c)
    p.drawEllipse(QPointF(12, 12), 8, 8)
    _poly(p, (12, 12), (12, 6.8))
    _poly(p, (12, 12), (16, 13.8))


def _snapshot(p: QPainter, c: str) -> None:
    _line(p, c)
    p.drawRoundedRect(QRectF(2.5, 7, 19, 12.5), 2, 2)
    _poly(p, (8.5, 7), (9.8, 4), (14.2, 4), (15.5, 7))
    p.drawEllipse(QPointF(12, 13.2), 3.4, 3.4)


def _search(p: QPainter, c: str) -> None:
    _line(p, c)
    p.drawEllipse(QPointF(10.5, 10.5), 6.5, 6.5)
    _poly(p, (15.2, 15.2), (20.5, 20.5))


def _fallback(p: QPainter, c: str) -> None:
    """未知名称的稳定回退：圆角方块 + 圆点。"""
    _line(p, c)
    p.drawRoundedRect(QRectF(5, 5, 14, 14), 3, 3)
    _fill(p, c)
    p.drawEllipse(QPointF(12, 12), 1.6, 1.6)


_PAINTERS = {
    "dashboard": _dashboard,
    "waveform": _waveform,
    "serial": _serial,
    "variable": _variable,
    "tuning": _tuning,
    "ai": _ai,
    "msg": _msg,
    "upgrade": _upgrade,
    "connect": _connect,
    "disconnect": _disconnect,
    "device": _device,
    "theme": _theme,
    "plus": _plus,
    "remove": _remove,
    "play": _play,
    "pause": _pause,
    "stop": _stop,
    "clear": _clear,
    "export": _export,
    "refresh": _refresh,
    "send": _send,
    "settings": _settings,
    "folder": _folder,
    "warning": _warning,
    "success": _success,
    "info": _info,
    "clock": _clock,
    "snapshot": _snapshot,
    "search": _search,
}

ICON_NAMES = tuple(_PAINTERS)


def paint_icon(painter: QPainter, name: str, rect, color: str) -> None:
    """在 rect 内以 color 绘制 name 图标（24×24 矢量网格自动等比居中）。

    侧边栏/按钮在 paintEvent 里直接调用本函数，即可随主题色实时重绘；
    未知名称绘制稳定回退图形。
    """
    target = QRectF(rect)
    side = min(target.width(), target.height())
    if side <= 0:
        return
    square = QRectF(0, 0, side, side)
    square.moveCenter(target.center())
    draw = _PAINTERS.get(name, _fallback)
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.translate(square.topLeft())
    painter.scale(side / _GRID, side / _GRID)
    draw(painter, color)
    painter.restore()


def icon(name: str, color: str, size: int = 18) -> QIcon:
    """返回预渲染的矢量 QIcon（按 size 与主屏幕 DPR 渲染，保证非空 pixmap）。"""
    dpr = 1.0
    app = QGuiApplication.instance()
    if app is not None and app.primaryScreen() is not None:
        dpr = app.primaryScreen().devicePixelRatio()
    px = max(1, round(size * dpr))
    pixmap = QPixmap(px, px)
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    paint_icon(painter, name, QRectF(0.0, 0.0, float(size), float(size)), color)
    painter.end()
    return QIcon(pixmap)
