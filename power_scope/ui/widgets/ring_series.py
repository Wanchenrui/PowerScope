"""ring_series.py — 定长环形时间序列缓冲（波形组件共用）

替代旧的 np.append 逐点拷贝（O(n)/点）：
  - append O(1)，容量封顶，最老样本自动被覆盖
  - windowed() 用 searchsorted 取时间窗切片（视图为切片，不拷贝）
  - 由消费方（PlotWidget）按 30Hz 定时器合帧重绘，避免逐点 setData
"""
import numpy as np


class RingSeries:
    """单通道 (t, v) 环形缓冲。t 需单调递增（相对时间）。"""

    def __init__(self, capacity: int = 4000, time_window: float = 10.0):
        self._cap = max(16, int(capacity))
        self._window = float(time_window)
        self._t = np.empty(self._cap, dtype=np.float64)
        self._v = np.empty(self._cap, dtype=np.float64)
        self._idx = 0       # 下一个写入位置
        self._count = 0     # 有效样本数（<= cap）
        self.dirty = False  # 自上次重绘后是否有新样本

    @property
    def time_window(self) -> float:
        return self._window

    @time_window.setter
    def time_window(self, value: float) -> None:
        self._window = max(0.05, float(value))
        self.dirty = True

    def append(self, t: float, v: float) -> None:
        self._t[self._idx] = t
        self._v[self._idx] = v
        self._idx = (self._idx + 1) % self._cap
        if self._count < self._cap:
            self._count += 1
        self.dirty = True

    def arrays(self):
        """按时间顺序返回 (t, v)。未满时为视图，环绕时为拼接拷贝。"""
        n = self._count
        if n == 0:
            return self._t[:0], self._v[:0]
        if n < self._cap:
            return self._t[:n], self._v[:n]
        t = np.concatenate((self._t[self._idx:], self._t[:self._idx]))
        v = np.concatenate((self._v[self._idx:], self._v[:self._idx]))
        return t, v

    def windowed(self):
        """返回时间窗内的 (t, v) 切片（保持与旧 mask 语义一致：t >= 最新t - 窗口）。"""
        t, v = self.arrays()
        if t.size == 0:
            return t, v
        cutoff = t[-1] - self._window
        if cutoff <= t[0]:
            return t, v
        start = int(np.searchsorted(t, cutoff, side="left"))
        return t[start:], v[start:]

    def windowed_count(self) -> int:
        """时间窗内样本数（不重绘也可查询，供 sample_count 使用）。"""
        return len(self.windowed()[0])

    def clear(self) -> None:
        self._idx = 0
        self._count = 0
        self.dirty = True
