"""bode_analyzer.py — Bode 图分析与频谱计算

基于 FFT 的频率响应分析，支持：
- 给定输入/输出信号，计算频率响应 H(jω)
- 幅频特性 (dB) 和相频特性 (度)
- 信号频谱分析 (PSD)

使用方式:
    analyzer = BodeAnalyzer()
    freq, mag_db, phase_deg = analyzer.frequency_response(
        input_signal, output_signal, sample_rate=10000
    )
"""
from __future__ import annotations
import numpy as np
from typing import Optional, Tuple


class BodeAnalyzer:
    """Bode 图分析器 — FFT 频率响应"""

    def __init__(self) -> None:
        pass

    # ------------------------------------------------------------------
    # 频率响应
    # ------------------------------------------------------------------

    def frequency_response(
        self,
        input_signal: np.ndarray,
        output_signal: np.ndarray,
        sample_rate: float,
        window: bool = True,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """计算频率响应 H(jω) = FFT(output) / FFT(input)

        Args:
            input_signal: 输入信号时间序列
            output_signal: 输出信号时间序列
            sample_rate: 采样率 (Hz)
            window: 是否加汉宁窗减少频谱泄漏

        Returns:
            (频率数组, 幅值 dB 数组, 相位度数组)
        """
        n = len(input_signal)
        if n != len(output_signal):
            raise ValueError("input and output must have same length")

        # 加窗减少频谱泄漏
        w = np.hanning(n) if window else np.ones(n)
        u = input_signal * w
        y = output_signal * w

        # FFT
        U = np.fft.rfft(u)
        Y = np.fft.rfft(y)
        freqs = np.fft.rfftfreq(n, d=1.0 / sample_rate)

        # 避免除以零
        eps = 1e-12
        H = Y / (U + eps)

        # 幅频 (dB)
        mag = np.abs(H)
        mag_db = 20 * np.log10(mag + eps)

        # 相频 (度)
        phase_deg = np.degrees(np.angle(H))

        return freqs, mag_db, phase_deg

    # ------------------------------------------------------------------
    # 频谱分析
    # ------------------------------------------------------------------

    def spectrum(
        self,
        signal: np.ndarray,
        sample_rate: float,
        window: bool = True,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """计算信号功率谱密度

        Returns:
            (频率数组, PSD 数组)
        """
        n = len(signal)
        w = np.hanning(n) if window else np.ones(n)
        s = signal * w
        S = np.fft.rfft(s)
        freqs = np.fft.rfftfreq(n, d=1.0 / sample_rate)
        psd = np.abs(S) ** 2 / (sample_rate * n)
        # 汉宁窗功率补偿
        if window:
            psd *= 2.0 / np.mean(w ** 2)
        return freqs, psd

    # ------------------------------------------------------------------
    # 阶跃响应分析
    # ------------------------------------------------------------------

    def step_response_metrics(
        self,
        output_signal: np.ndarray,
        sample_rate: float,
        step_time_idx: int = 0,
    ) -> dict:
        """分析阶跃响应指标

        Args:
            output_signal: 输出信号
            sample_rate: 采样率
            step_time_idx: 阶跃发生时刻的索引

        Returns:
            dict: overshoot, rise_time, settling_time, steady_state_error
        """
        y = output_signal[step_time_idx:]
        if len(y) == 0:
            return {}

        # 稳态值（后 20% 平均值）
        steady_state = np.mean(y[int(0.8 * len(y)):])
        y_norm = y / steady_state if steady_state != 0 else y

        # 超调量 (%)
        overshoot = (np.max(y_norm) - 1.0) * 100.0

        # 上升时间 (10% -> 90%)
        t_10 = np.where(y_norm >= 0.1)[0]
        t_90 = np.where(y_norm >= 0.9)[0]
        rise_time = (t_90[0] - t_10[0]) / sample_rate if len(t_10) > 0 and len(t_90) > 0 else None

        # 调节时间 (进入 ±5% 带)
        within_band = np.abs(y_norm - 1.0) <= 0.05
        settling_idx = None
        for i in range(len(within_band) - 1, -1, -1):
            if not within_band[i]:
                settling_idx = i + 1
                break
        settling_time = settling_idx / sample_rate if settling_idx is not None else None

        return {
            "overshoot_percent": overshoot,
            "rise_time_s": rise_time,
            "settling_time_s": settling_time,
            "steady_state": steady_state,
        }

    # ------------------------------------------------------------------
    # 共振频率检测
    # ------------------------------------------------------------------

    def find_peaks(
        self,
        freqs: np.ndarray,
        mag_db: np.ndarray,
        min_prominence: float = 3.0,
        min_freq: float = 0.0,
    ) -> list[dict]:
        """检测频率响应中的峰值（共振点）

        Returns:
            list of {"freq": float, "mag_db": float, "prominence": float}
        """
        peaks = []
        for i in range(1, len(mag_db) - 1):
            if mag_db[i] <= mag_db[i - 1] or mag_db[i] <= mag_db[i + 1]:
                continue
            if freqs[i] < min_freq:
                continue

            # 向左找谷值
            left_min = mag_db[i]
            j = i - 1
            while j >= 0 and mag_db[j] < mag_db[i]:
                left_min = min(left_min, mag_db[j])
                j -= 1

            # 向右找谷值
            right_min = mag_db[i]
            j = i + 1
            while j < len(mag_db) and mag_db[j] < mag_db[i]:
                right_min = min(right_min, mag_db[j])
                j += 1

            baseline = max(left_min, right_min)
            prominence = mag_db[i] - baseline
            if prominence >= min_prominence:
                peaks.append({
                    "freq": freqs[i],
                    "mag_db": mag_db[i],
                    "prominence": prominence,
                })
        return sorted(peaks, key=lambda p: p["prominence"], reverse=True)
