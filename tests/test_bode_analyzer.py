"""test_bode_analyzer.py — Bode 图分析器测试"""
import numpy as np
import pytest
from power_scope.core.bode_analyzer import BodeAnalyzer


class TestBodeAnalyzerFrequencyResponse:
    def test_create(self):
        analyzer = BodeAnalyzer()
        assert analyzer is not None

    def test_frequency_response_sine(self):
        """输入输出为同频正弦，频率响应应为 0 dB / 0°"""
        analyzer = BodeAnalyzer()
        sr = 10000
        t = np.linspace(0, 1, sr, endpoint=False)
        freq = 50.0
        u = np.sin(2 * np.pi * freq * t)
        y = np.sin(2 * np.pi * freq * t)  # 增益 1，相位 0

        freqs, mag_db, phase_deg = analyzer.frequency_response(u, y, sr)

        # 找到最接近 50 Hz 的频率点
        idx = np.argmin(np.abs(freqs - freq))
        assert mag_db[idx] < 3.0  # 接近 0 dB
        assert mag_db[idx] > -3.0
        assert np.abs(phase_deg[idx]) < 10.0  # 接近 0°

    def test_frequency_response_gain(self):
        """输出 = 2 * 输入，频率响应应为 6 dB"""
        analyzer = BodeAnalyzer()
        sr = 10000
        t = np.linspace(0, 1, sr, endpoint=False)
        freq = 50.0
        u = np.sin(2 * np.pi * freq * t)
        y = 2.0 * u

        freqs, mag_db, phase_deg = analyzer.frequency_response(u, y, sr)
        idx = np.argmin(np.abs(freqs - freq))
        assert np.abs(mag_db[idx] - 6.0) < 2.0  # 约 6 dB

    def test_frequency_response_phase_shift(self):
        """输出相位延迟 90°"""
        analyzer = BodeAnalyzer()
        sr = 10000
        t = np.linspace(0, 1, sr, endpoint=False)
        freq = 50.0
        u = np.sin(2 * np.pi * freq * t)
        y = np.sin(2 * np.pi * freq * t - np.pi / 2)

        freqs, mag_db, phase_deg = analyzer.frequency_response(u, y, sr)
        idx = np.argmin(np.abs(freqs - freq))
        assert np.abs(phase_deg[idx] + 90.0) < 15.0  # 约 -90°

    def test_length_mismatch_raises(self):
        analyzer = BodeAnalyzer()
        with pytest.raises(ValueError):
            analyzer.frequency_response(
                np.zeros(100), np.zeros(50), 10000
            )


class TestBodeAnalyzerSpectrum:
    def test_spectrum_peak(self):
        """50 Hz 正弦信号，频谱应在 50 Hz 处有峰值"""
        analyzer = BodeAnalyzer()
        sr = 10000
        t = np.linspace(0, 1, sr, endpoint=False)
        freq = 50.0
        s = np.sin(2 * np.pi * freq * t)

        freqs, psd = analyzer.spectrum(s, sr)
        idx = np.argmax(psd)
        assert np.abs(freqs[idx] - freq) < 2.0

    def test_spectrum_two_tones(self):
        """50 Hz + 150 Hz 合成信号"""
        analyzer = BodeAnalyzer()
        sr = 10000
        t = np.linspace(0, 1, sr, endpoint=False)
        s = np.sin(2 * np.pi * 50 * t) + 0.5 * np.sin(2 * np.pi * 150 * t)

        freqs, psd = analyzer.spectrum(s, sr)
        # 50 Hz 应该是最高峰值
        idx50 = np.argmin(np.abs(freqs - 50))
        idx150 = np.argmin(np.abs(freqs - 150))
        assert psd[idx50] > psd[idx150]


class TestBodeAnalyzerStepResponse:
    def test_step_response_overshoot(self):
        """模拟二阶欠阻尼阶跃响应"""
        analyzer = BodeAnalyzer()
        sr = 10000
        t = np.linspace(0, 1, sr, endpoint=False)
        # 阻尼比 0.3，自然频率 10 Hz
        zeta, wn = 0.3, 2 * np.pi * 10
        wd = wn * np.sqrt(1 - zeta**2)
        y = 1.0 - np.exp(-zeta * wn * t) * (
            np.cos(wd * t) + (zeta / np.sqrt(1 - zeta**2)) * np.sin(wd * t)
        )

        metrics = analyzer.step_response_metrics(y, sr)
        assert metrics["overshoot_percent"] > 0  # 有超调
        assert metrics["rise_time_s"] is not None
        assert metrics["settling_time_s"] is not None

    def test_step_response_no_overshoot(self):
        """过阻尼阶跃响应，无超调"""
        analyzer = BodeAnalyzer()
        sr = 1000
        t = np.linspace(0, 1, sr, endpoint=False)
        # 简单指数趋近
        y = 1.0 - np.exp(-5 * t)

        metrics = analyzer.step_response_metrics(y, sr)
        assert metrics["overshoot_percent"] <= 1.0  # 允许微小数值误差


class TestBodeAnalyzerFindPeaks:
    def test_find_resonance(self):
        """创建有明确共振峰的频率响应"""
        analyzer = BodeAnalyzer()
        freqs = np.linspace(1, 1000, 1000)
        # 模拟 200 Hz 处的共振峰
        mag_db = -20 * np.log10(freqs / 10)  # 基础衰减
        mag_db += 15 * np.exp(-((freqs - 200) / 20) ** 2)  # 200 Hz 共振峰
        mag_db += 8 * np.exp(-((freqs - 500) / 30) ** 2)  # 500 Hz 小峰

        peaks = analyzer.find_peaks(freqs, mag_db, min_prominence=3.0)
        assert len(peaks) >= 1
        assert np.abs(peaks[0]["freq"] - 200) < 5.0

    def test_no_peaks(self):
        analyzer = BodeAnalyzer()
        freqs = np.linspace(1, 100, 100)
        mag_db = np.zeros(100)
        peaks = analyzer.find_peaks(freqs, mag_db, min_prominence=3.0)
        assert len(peaks) == 0
