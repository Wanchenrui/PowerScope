"""streaming_manager.py — 采样通道集合管理（从 MainWindow 抽离，纯逻辑可单测）。

只负责"当前要流式采集哪些通道"的状态与计算：
  - 慢速 profile/监视通道与 25us 示波器通道严格分离
  - 采样周期计算、单列表 32 通道上限截断
不涉及 Qt/串口 IO（那部分仍由 MainWindow 编排），因此可脱离 GUI 单测。
"""
from __future__ import annotations


class StreamingManager:
    MAX_CHANNELS = 32

    def __init__(self):
        self.profile_channels: dict = {}   # name -> SampleChannel（profile 变量，常驻）
        self.monitor_channels: dict = {}   # name -> SampleChannel（慢速临时监视）
        self.extra_channels: dict = {}     # name -> SampleChannel（高速示波器，兼容旧属性名）
        self.streaming: bool = False
        self.stream_list_id: int = 0

    # ---- 通道集合 ----
    def set_profile_channels(self, channels) -> None:
        self.profile_channels = {c.name: c for c in channels}

    def add_extra(self, name, channel) -> bool:
        """加入临时通道；返回 True 表示是新加入（原本不存在）。"""
        new = name not in self.extra_channels
        self.extra_channels[name] = channel
        return new

    def remove_extra(self, name) -> bool:
        """移除临时通道；返回是否确实移除。"""
        return self.extra_channels.pop(name, None) is not None

    def stream_set(self) -> dict:
        """慢速 List 0：profile 常驻 + 显式慢速监视。"""
        merged = dict(self.profile_channels)
        merged.update(self.monitor_channels)
        return merged

    def scope_set(self) -> dict:
        """高速 List 1/Wave：只含用户明确加入示波器的通道。"""
        return dict(self.extra_channels)

    def add_monitor(self, name, channel) -> bool:
        new = name not in self.monitor_channels
        self.monitor_channels[name] = channel
        return new

    def remove_monitor(self, name) -> bool:
        return self.monitor_channels.pop(name, None) is not None

    def channel_list(self):
        """下发用的通道列表，超过上限截断；返回 (channels, truncated)。"""
        chans = list(self.stream_set().values())
        if len(chans) > self.MAX_CHANNELS:
            return chans[:self.MAX_CHANNELS], True
        return chans, False

    # ---- 采样周期 ----
    @staticmethod
    def compute_period_us(variables) -> int:
        """按 profile 变量的最小 update_rate(ms) 计算采样周期(us)，钳到 [100, 65535]。"""
        rates = [v.update_rate for v in variables if getattr(v, "update_rate", 0) > 0]
        period_ms = min(rates) if rates else 20
        return max(100, min(period_ms * 1000, 65535))
