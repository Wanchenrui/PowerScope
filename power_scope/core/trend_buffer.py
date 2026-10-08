"""trend_buffer.py — 数值趋势环形缓冲 + 变化量分析（P0-2 的纯逻辑层）

仪表盘卡片消费：
  - TrendBuffer: 定容环形缓冲，append 自动淘汰最旧样本
  - Snapshot.delta(): 与上一次公开值的差 → 方向箭头（↑/↓/=）与变化率

与 UI 解耦：不 import Qt，可独立单测；widgets/sparkline.py 只负责绘制。
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class Delta:
    """相邻两次值的变化。"""

    direction: str        # "up" / "down" / "flat"
    absolute: float       # 绝对变化量
    percent: float        # 相对变化量（%，以上一值为基；上一值为 0 时为 ±inf/0）


def analyze_delta(previous: float | None, current: float,
                  epsilon: float = 1e-9) -> Delta:
    """比较前值与当前值，输出方向/绝对差/相对差。"""
    if previous is None:
        return Delta("flat", 0.0, 0.0)
    diff = float(current) - float(previous)
    if abs(diff) <= epsilon:
        return Delta("flat", 0.0, 0.0)
    direction = "up" if diff > 0 else "down"
    if previous == 0:
        percent = float("inf") if diff > 0 else float("-inf")
    else:
        percent = diff / abs(float(previous)) * 100.0
    return Delta(direction, diff, percent)


class TrendBuffer:
    """定容 (t, value) 环形缓冲。"""

    __slots__ = ("_capacity", "_points")

    def __init__(self, capacity: int = 64):
        self._capacity = max(2, int(capacity))
        self._points: deque = deque(maxlen=self._capacity)

    @property
    def capacity(self) -> int:
        return self._capacity

    def clear(self) -> None:
        self._points.clear()

    def append(self, timestamp: float, value: float) -> None:
        try:
            self._points.append((float(timestamp), float(value)))
        except (TypeError, ValueError):
            return

    def __len__(self) -> int:
        return len(self._points)

    def values(self) -> list[float]:
        return [v for _t, v in self._points]

    def timestamps(self) -> list[float]:
        return [t for t, _v in self._points]

    def points(self) -> list[tuple[float, float]]:
        return list(self._points)

    def last(self) -> float | None:
        if not self._points:
            return None
        return self._points[-1][1]

    def min_max(self) -> tuple[float, float] | None:
        """窗口内 (min, max)；空窗口返回 None（供 sparkline 归一化）。"""
        if not self._points:
            return None
        vals = [v for _t, v in self._points]
        return min(vals), max(vals)
