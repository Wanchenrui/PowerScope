"""power_simulator.py — 电力电子环路 PID 阶跃响应离线仿真

不依赖 MCU/硬件/串口 —— 纯 numpy 数值计算。支持：
- 一阶纯滞后(FOPDT)  + PID
- 二阶系统(ζ,ωn)     + PID
- 精确零阶保持(ZOH)离散，对刚性/高频对象无条件稳定
- 输出 (t, y) 格式与 analyze_step 兼容

典型电力电子被控对象：
- DC母线电压环：G(s) = 1/(sC)，一阶积分型 → FOPDT K=1/C, T=0
- LCL滤波器电流环：二阶欠阻尼
- Boost升压电感电流：RL一阶 G(s) = 1/(Ls+R)

用法:
    plant = PlantModel.first_order(K=10.0, T=0.005, L=0.001)
    t, y = simulate_step(plant, Kp=0.8, Ki=160.0, Kd=0.001, amplitude=1.0)
    metrics = analyze_step(list(zip(t, y)), t_step=0.0, input_step=1.0)
"""

from __future__ import annotations
from dataclasses import dataclass
import numpy as np


# ═══════════════════════════════════════════════════════════════════
# 数据类型
# ═══════════════════════════════════════════════════════════════════

@dataclass
class PlantModel:
    """连续系统被控对象。

    字段:
        kind: "first_order" | "second_order" | "integrator"
        K:   直流增益
        T:   时间常数(秒)  — first_order 用
        L:   纯滞后(秒)    — first_order 用
        zeta: 阻尼比       — second_order 用
        wn:   自然频率(rad/s) — second_order 用
    """
    kind: str = "first_order"
    K: float = 1.0
    T: float = 0.01
    L: float = 0.0
    zeta: float = 0.7
    wn: float = 628.0       # ≈100Hz

    @classmethod
    def first_order(cls, K: float, T: float, L: float = 0.0) -> "PlantModel":
        """创建一阶纯滞后模型 G(s) = K·e^(-Ls) / (Ts+1)。"""
        return cls(kind="first_order", K=K, T=T, L=L)

    @classmethod
    def second_order(cls, K: float, zeta: float, wn: float) -> "PlantModel":
        """创建二阶模型 G(s) = K·ωn² / (s² + 2ζωn s + ωn²)。"""
        return cls(kind="second_order", K=K, zeta=zeta, wn=wn)

    @classmethod
    def integrator(cls, K: float, L: float = 0.0) -> "PlantModel":
        """积分器 G(s) = K·e^(-Ls) / s（DC 母线电容等）。"""
        return cls(kind="integrator", K=K, T=0.0, L=L)

    def to_label(self) -> str:
        """人类可读的模型描述。"""
        if self.kind == "first_order":
            s = f"G(s)=K/(Ts+1), K={self.K:.4g}, T={self.T*1e3:.2f}ms"
            if self.L > 0:
                s += f", L={self.L*1e6:.0f}μs"
            return s
        elif self.kind == "second_order":
            return f"G(s)=Kωn²/(s²+2ζωn+ωn²), K={self.K:.4g}, ζ={self.zeta:.2f}, ωn={self.wn:.0f}"
        else:
            return f"G(s)=K/s, K={self.K:.4g}" + (f", L={self.L*1e6:.0f}μs" if self.L > 0 else "")


# ═══════════════════════════════════════════════════════════════════
# 数值工具
# ═══════════════════════════════════════════════════════════════════

def _expm2(M: np.ndarray) -> np.ndarray:
    """2×2 实矩阵指数（特征分解法，支持复特征值/欠阻尼）。"""
    w, V = np.linalg.eig(M)
    return (V @ np.diag(np.exp(w)) @ np.linalg.inv(V)).real


def _c2d_zoh(A: np.ndarray, B: np.ndarray, dt: float):
    """连续状态空间 (A,B) 的零阶保持离散：Ad=expm(A·dt), Bd=A⁻¹(Ad−I)B。

    A 在本模块（阻尼振荡器）恒可逆（det=ωn²>0），故闭式成立。
    """
    Ad = _expm2(A * dt)
    Bd = np.linalg.solve(A, (Ad - np.eye(A.shape[0])) @ B)
    return Ad, Bd


def _pick_dt(plant: "PlantModel", duration: float, dt_req: float) -> float:
    """选内部仿真步长：兼顾控制器采样精度，plant 侧用精确离散故无稳定性约束。"""
    dt_eff = dt_req
    if plant.kind == "first_order" and plant.T > 0:
        dt_eff = min(dt_eff, 0.1 * plant.T)
    elif plant.kind == "second_order" and plant.wn > 0:
        dt_eff = min(dt_eff, 0.05 * (2 * np.pi / plant.wn))
    else:  # integrator
        dt_eff = min(dt_eff, duration / 500.0)
    return max(dt_eff, 1e-9)


# ═══════════════════════════════════════════════════════════════════
# 仿真核心
# ═══════════════════════════════════════════════════════════════════

def simulate_step(plant: PlantModel,
                  Kp: float, Ki: float, Kd: float,
                  amplitude: float = 1.0,
                  duration: float = 0.1,
                  dt: float = 1e-4,
                  N: float = 1000.0,
                  sat_max: float = 100.0) -> tuple:
    """仿真 PID 闭环单位反馈阶跃响应。

    Args:
        plant: 被控对象模型
        Kp, Ki, Kd: PID 增益（并行形式）
        amplitude: 阶跃幅值
        duration: 仿真时长(秒)
        dt: 期望输出步长(秒)；内部仿真会自动细分并重采样回该栅格
        N: 微分滤波器系数 (D term = Kd*s/(1+s/N))
        sat_max: 控制量饱和限幅（抗积分饱和 + 输出钳位）

    Returns:
        (t, y) — t: 1D numpy 时间数组(秒)；y: 1D numpy 输出数组(幅值单位)

    算法:
        - 被控对象用精确零阶保持(ZOH)离散（无条件稳定，含高频/刚性对象）
        - 控制器在细分步长上运行：梯形积分(带 back-calculation 抗饱和) + 一阶低通滤波微分
        - 纯滞后用 ring buffer 实现（L/dt_eff 取整）
    """
    dt_eff = _pick_dt(plant, duration, dt)
    n_steps = int(round(duration / dt_eff)) + 1
    dt_eff = duration / (n_steps - 1) if n_steps > 1 else dt_eff
    # 纯滞后步数
    L_steps = max(0, int(round(plant.L / dt_eff)))
    # 输出饱和限
    sat_lo = -sat_max
    sat_hi = sat_max

    # --- 被控对象离散（精确 ZOH） ---
    if plant.kind == "first_order":
        if plant.T <= 0:
            # 纯积分器 dy/dt = K·u（u 恒定时精确）
            a_d = 1.0
            b_d = plant.K * dt_eff
        else:
            # dy/dt = (K·u - y)/T → 精确: y_{k+1}=exp(-dt/T)·y_k + K·(1-exp(-dt/T))·u
            a_d = np.exp(-dt_eff / plant.T)
            b_d = plant.K * (1.0 - a_d)
    elif plant.kind == "second_order":
        A = np.array([[0.0, 1.0],
                      [-plant.wn ** 2, -2 * plant.zeta * plant.wn]])
        B = np.array([[0.0], [plant.K * plant.wn ** 2]])
        Ad, Bd = _c2d_zoh(A, B, dt_eff)
        Bd = Bd.flatten()
        x = np.zeros(2)
    else:  # integrator with gain
        a_d = 1.0
        b_d = plant.K * dt_eff

    # --- 仿真循环 ---
    t = np.linspace(0, duration, n_steps)
    y = np.zeros(n_steps)
    y[0] = 0.0

    # 控制器状态
    int_sum = 0.0    # 梯形积分累加器
    d_filt = 0.0     # 微分滤波器输出
    e_prev = 0.0     # 上一拍误差
    u_prev = 0.0     # 上一拍控制量

    # 纯滞后缓冲（对控制量做滞后）
    if L_steps > 0:
        delay_buf = np.zeros(L_steps + 1)
        delay_ptr = 0
    else:
        delay_buf = None

    sp = amplitude  # 设定值（阶跃）

    for k in range(1, n_steps):
        # 当前输出
        if plant.kind == "second_order":
            x_new = Ad @ x + Bd * u_prev
            yk = x_new[0]
            x = x_new
        else:
            if L_steps > 0:
                # 从延迟缓冲区取滞后控制量
                delay_buf[delay_ptr] = u_prev
                delay_ptr = (delay_ptr + 1) % (L_steps + 1)
                u_delayed = delay_buf[delay_ptr]
                yk = a_d * y[k - 1] + b_d * u_delayed
            else:
                yk = a_d * y[k - 1] + b_d * u_prev
        y[k] = yk

        # PID 控制器
        e = sp - yk

        # 比例项
        p = Kp * e

        # 梯形积分（带抗饱和：先算预控制量，超限则回退积分增量）
        di = (e + e_prev) * dt_eff * 0.5  # 积分增量
        int_trial = int_sum + di
        # 滤波微分：D(s) = Kd·s/(1+s/N)
        if Kd > 0 and N > 0:
            d_filt = (d_filt + Kd * N * (e - e_prev)) / (1.0 + N * dt_eff)
            d = d_filt
        else:
            d = 0.0

        # 预控制量
        u_trial = p + Ki * int_trial + d

        # 抗饱和：超限则仅累加可容纳的积分增量（back-calculation）
        if u_trial > sat_hi:
            u = sat_hi
            if Ki > 0 and not np.isnan(di):
                # 回退积分：只累加刚好让 u 到上限的部分（钳到 [int_sum,int_trial] 单调区间）
                allowed_i = (sat_hi - p - d) / Ki
                lo, hi = min(int_sum, int_trial), max(int_sum, int_trial)
                int_sum = float(np.clip(allowed_i, lo, hi))
            else:
                int_sum = int_trial
        elif u_trial < sat_lo:
            u = sat_lo
            if Ki > 0 and not np.isnan(di):
                allowed_i = (sat_lo - p - d) / Ki
                lo, hi = min(int_sum, int_trial), max(int_sum, int_trial)
                int_sum = float(np.clip(allowed_i, lo, hi))
            else:
                int_sum = int_trial
        else:
            u = u_trial
            int_sum = int_trial

        u_prev = u
        e_prev = e

    # 重采样回期望输出栅格（内部步长可能被细分）
    n_out = int(round(duration / dt)) + 1
    if n_out != n_steps and n_out > 1:
        t_out = np.linspace(0, duration, n_out)
        y_out = np.interp(t_out, t, y)
        return t_out, y_out
    return t, y


# ═══════════════════════════════════════════════════════════════════
# 便捷函数 — 与现有 analyze_step 连线
# ═══════════════════════════════════════════════════════════════════

def simulate_and_analyze(plant: PlantModel,
                         Kp: float, Ki: float, Kd: float,
                         amplitude: float = 1.0,
                         duration: float = 0.1,
                         dt: float = 1e-4) -> "StepMetrics":
    """仿真阶跃响应并返回 StepMetrics（一步完成仿真+分析）。

    用法:
        m = simulate_and_analyze(PlantModel.first_order(10,0.005), 0.5,100,0)
        print(f"超调={m.overshoot_pct}%, 上升={m.rise_time_ms}ms")
        pid = m.to_system_metrics()  # 喂给 TuningEngine
    """
    from .step_response import analyze_step
    t, y = simulate_step(plant, Kp, Ki, Kd, amplitude, duration, dt)
    samples = [(float(ti), float(yi)) for ti, yi in zip(t, y)]
    return analyze_step(samples, t_step=0.0, input_step=amplitude, baseline=0.0)


# ═══════════════════════════════════════════════════════════════════
# 推荐预设 — 电力电子典型被控对象
# ═══════════════════════════════════════════════════════════════════

PRESET_PLANTS = {
    "电流内环 (LCL滤波)": PlantModel.second_order(K=1.0, zeta=0.3, wn=2000.0),
    "电流内环 (RL电感)": PlantModel.first_order(K=0.5, T=0.002),
    "电压外环 (DC母线)": PlantModel.integrator(K=0.01),
    "Boost升压电感": PlantModel.first_order(K=0.2, T=0.01, L=0.0005),
    "VSG频率环": PlantModel.first_order(K=0.05, T=0.05),
    "Buck-降压": PlantModel.first_order(K=2.0, T=0.005, L=0.0001),
    "二阶欠阻尼 (通用)": PlantModel.second_order(K=1.0, zeta=0.3, wn=628.0),
}

# ═══════════════════════════════════════════════════════════════════
# 整定前后闭环对比 — 下发前预估改善
# ═══════════════════════════════════════════════════════════════════

def compare_pid(plant: PlantModel,
                old_gains: tuple,
                new_gains: tuple,
                amplitude: float = 1.0,
                duration: float = None,
                dt: float = None) -> dict:
    """用同一被控对象仿真「旧参数」与「新参数」的闭环阶跃，返回两条曲线与指标。

    Args:
        plant: 被控对象
        old_gains / new_gains: (Kp, Ki, Kd)
        amplitude: 阶跃幅值
        duration: 仿真时长(秒)；None 时按 plant 时间常数自适应
        dt: 输出步长；None 时自适应

    Returns:
        {
          "old": {"t": np.ndarray, "y": np.ndarray, "metrics": StepMetrics},
          "new": {...同上...},
          "duration": float, "dt": float,
        }
    """
    from .step_response import analyze_step

    # 自适应时长：一阶看 T+L，二阶看 1/wn；取足够覆盖调节过程
    if duration is None:
        if plant.kind == "second_order" and plant.wn > 0:
            duration = max(0.02, 40.0 / plant.wn)
        else:
            T = plant.T if plant.T > 0 else 0.02
            duration = max(0.02, 18.0 * T + 6.0 * plant.L)
    if dt is None:
        dt = duration / 2000.0

    def _run(gains):
        kp, ki, kd = gains
        t, y = simulate_step(plant, kp, ki, kd, amplitude=amplitude,
                             duration=duration, dt=dt)
        samples = [(float(ti), float(yi)) for ti, yi in zip(t, y)]
        m = analyze_step(samples, t_step=0.0, input_step=amplitude, baseline=0.0)
        return t, y, m

    ot, oy, om = _run(old_gains)
    nt, ny, nm = _run(new_gains)
    return {
        "old": {"t": ot, "y": oy, "metrics": om},
        "new": {"t": nt, "y": ny, "metrics": nm},
        "duration": duration, "dt": dt,
    }

