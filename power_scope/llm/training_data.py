"""
training_data.py — 神经网络训练数据生成

基于控制理论公式和二阶系统仿真生成训练数据:
  输入: [超调, 上升时间, 调节时间, 稳态误差, 当前Kp, 当前Ki, 当前Kd, 目标超调]
  输出: [最优Kp, 最优Ki, 最优Kd]

数据来源:
  1. Ziegler-Nichols 法 (临界增益 Ku + 临界周期 Tu)
  2. Cohen-Coon 法 (增益 K + 时间常数 T + 滞后 L)
  3. IMC 内模控制法
  4. 二阶系统阶跃响应仿真
"""
import math
import random
import numpy as np


def second_order_time_metrics(zeta: float, wn: float) -> tuple:
    """标准二阶系统单位阶跃的解析指标 (超调%, 上升时间ms, 调节时间ms)。

    解析式代替数值积分，杜绝显式欧拉在高 wn/小阻尼下的发散。
    """
    z = max(1e-3, float(zeta))
    if z < 1.0:
        root = math.sqrt(1 - z * z)
        wd = wn * root
        overshoot = 100.0 * math.exp(-math.pi * z / root)
        rise = (math.pi - math.acos(z)) / wd          # 0→100% 上升时间(s)
        settling = 4.0 / (z * wn)                      # ±2% 调节时间(s)
    else:
        overshoot = 0.0
        rise = 2.2 / wn                                # 近似
        settling = 4.0 / (z * wn)
    return overshoot, rise * 1000.0, settling * 1000.0


def simulate_second_order_step(K: float, zeta: float, wn: float, dt: float = 0.001,
                                duration: float = 0.5) -> dict:
    """返回二阶系统阶跃响应性能指标（解析式，数值稳定）。

    G(s) = K * wn^2 / (s^2 + 2*zeta*wn*s + wn^2)
    dt/duration 参数保留以兼容旧签名，内部改用解析式不再数值积分。
    """
    overshoot, rise_time, settling_time = second_order_time_metrics(zeta, wn)
    return {
        "overshoot": min(overshoot, 50),
        "rise_time": max(rise_time, 1),
        "settling_time": max(min(settling_time, duration * 1000), 5),
        "steady_error": 0,          # 单位反馈二阶系统无稳态误差
        "steady_state": K,
    }

def ziegler_nichols_pid(Ku: float, Tu: float) -> dict:
    """Ziegler-Nichols PID 整定"""
    return {
        "kp": 0.6 * Ku,
        "ki": 1.2 * Ku / Tu,
        "kd": 0.075 * Ku * Tu,
    }


def cohen_coon_pid(K: float, T: float, L: float) -> dict:
    """Cohen-Coon PID 整定"""
    R = K * L / T
    return {
        "kp": 1.35 / R * (1 + 0.18 * L / (T - L * 0.18)) if T > L * 0.18 else 1.35 / R,
        "ki": 2.5 * K * L / (T * (T + 0.39 * L)) * 1000 if T > 0 else 0,
        "kd": 0.37 * K * L * T / (T + 0.2 * L) * 0.001 if T > 0 else 0,
    }


def imc_pid(K: float, T: float, L: float, tau_c: float = None) -> dict:
    """IMC 内模控制 PID 整定"""
    if tau_c is None:
        tau_c = max(T * 0.1, L * 2)
    return {
        "kp": T / (K * (tau_c + L)),
        "ki": T / (K * (tau_c + L) * L) if L > 0 else 0,
        "kd": L / (2 * (tau_c + L)) * T / K,
    }


def generate_training_data(n_samples: int = 2000, seed: int = 42,
                           noise_std: float = 0.02, val_split: float = 0.15) -> tuple:
    """
    生成训练数据（含测量噪声模拟 + 训练/验证集划分）

    Args:
        n_samples: 总样本数
        seed: 随机种子
        noise_std: 输入特征的高斯噪声标准差（相对值，模拟传感器测量噪声）
        val_split: 验证集比例 (0-1)

    Returns:
        (X_train, y_train, X_val, y_val) 四个列表
    """
    random.seed(seed)
    np.random.seed(seed)

    X = []
    y = []

    for _ in range(n_samples):
        # 随机生成二阶系统参数
        K = random.uniform(0.5, 3.0)
        zeta = random.uniform(0.1, 1.2)  # 阻尼比
        wn = random.uniform(50, 500)      # 自然频率 rad/s

        # 仿真阶跃响应
        metrics = simulate_second_order_step(K, zeta, wn)

        # 估算等效一阶参数 (用于 Cohen-Coon / IMC)
        T_equiv = 1.0 / (zeta * wn) if zeta * wn > 0 else 0.1
        L_equiv = 0.3 * T_equiv  # 估算纯滞后

        # 随机选择整定方法
        method = random.choice(["zn", "cohen", "imc"])

        if method == "zn":
            Ku = K * wn / (2 * zeta) * 2
            Tu = 2 * math.pi / (wn * math.sqrt(1 - zeta**2)) if zeta < 1 else 0.05
            Tu = max(Tu, 0.01)
            opt = ziegler_nichols_pid(Ku, Tu)
        elif method == "cohen":
            opt = cohen_coon_pid(K, T_equiv, L_equiv)
        else:
            tau_c = random.uniform(0.05, 0.3)
            opt = imc_pid(K, T_equiv, L_equiv, tau_c)

        # 当前参数 (在最优值附近随机扰动，模拟"待优化的参数")
        current_kp = opt["kp"] * random.uniform(0.5, 1.5)
        current_ki = opt["ki"] * random.uniform(0.5, 1.5)
        current_kd = opt["kd"] * random.uniform(0.3, 2.0)

        # 目标超调
        target_overshoot = random.choice([3, 5, 8, 10, 15])

        # 如果当前超调大于目标，减小增益；反之增大
        if metrics["overshoot"] > target_overshoot:
            adj = random.uniform(0.7, 0.95)
            opt["kp"] *= adj
            opt["kd"] *= random.uniform(1.1, 1.5)
        elif metrics["overshoot"] < target_overshoot * 0.5:
            opt["kp"] *= random.uniform(1.05, 1.2)
            opt["ki"] *= random.uniform(1.1, 1.3)

        # 限幅
        opt["kp"] = max(0, min(5, opt["kp"]))
        opt["ki"] = max(0, min(2000, opt["ki"]))
        opt["kd"] = max(0, min(0.5, opt["kd"]))

        # --- 添加测量噪声（模拟真实传感器/示波器测量误差） ---
        noisy_overshoot = metrics["overshoot"] + np.random.normal(0, metrics["overshoot"] * noise_std + 0.1)
        noisy_rise_time = metrics["rise_time"] + np.random.normal(0, metrics["rise_time"] * noise_std + 0.5)
        noisy_settling = metrics["settling_time"] + np.random.normal(0, metrics["settling_time"] * noise_std + 1.0)
        noisy_steady_err = metrics["steady_error"] + abs(np.random.normal(0, 0.05))

        # 确保非负
        noisy_overshoot = max(0, noisy_overshoot)
        noisy_rise_time = max(0.5, noisy_rise_time)
        noisy_settling = max(1, noisy_settling)
        noisy_steady_err = max(0, noisy_steady_err)

        # 构建训练样本
        X.append([
            noisy_overshoot,
            noisy_rise_time,
            noisy_settling,
            noisy_steady_err,
            current_kp,
            current_ki,
            current_kd,
            target_overshoot,
        ])
        y.append([opt["kp"], opt["ki"], opt["kd"]])

    # 划分训练/验证集
    n_val = int(n_samples * val_split)
    indices = list(range(n_samples))
    random.shuffle(indices)
    val_idx = set(indices[:n_val])
    train_idx = set(indices[n_val:])

    X_train = [X[i] for i in train_idx]
    y_train = [y[i] for i in train_idx]
    X_val = [X[i] for i in val_idx]
    y_val = [y[i] for i in val_idx]

    return X_train, y_train, X_val, y_val


def generate_feedback_data(current_kp: float, current_ki: float, current_kd: float,
                            overshoot: float, rise_time: float, settling_time: float,
                            steady_error: float, good_result: bool,
                            target_overshoot: float = 5.0) -> tuple:
    """
    根据用户反馈生成训练样本

    如果结果好: 当前参数就是"最优"目标
    如果结果差: 生成调整后的目标参数
    """
    if good_result:
        target = [current_kp, current_ki, current_kd]
    else:
        # 根据问题调整
        if overshoot > target_overshoot:
            target = [current_kp * 0.85, current_ki, min(current_kd + 0.01, 0.5)]
        else:
            target = [min(current_kp * 1.15, 5), min(current_ki * 1.2, 2000), current_kd]

    features = [overshoot, rise_time, settling_time, steady_error,
                current_kp, current_ki, current_kd, target_overshoot]
    return features, target

# ────────────────────────────────────────────────────────────────
# 闭环仿真标签生成 —— 用稳定的 power_simulator 网格搜索"最优 PID"作监督标签
# ────────────────────────────────────────────────────────────────

def _grid_best_pid(plant, target_overshoot, amplitude=1.0):
    """对给定对象网格搜索使闭环成本最小的 PID。返回 (cost, (kp,ki,kd), metrics) 或 None。"""
    from ..core.power_simulator import simulate_and_analyze
    kp_grid = [0.1, 0.3, 0.6, 1.0, 1.6, 2.5]
    ki_grid = [5, 20, 60, 150, 400]
    kd_grid = [0.0, 0.005, 0.02]
    best = None
    for kp in kp_grid:
        for ki in ki_grid:
            for kd in kd_grid:
                try:
                    m = simulate_and_analyze(plant, kp, ki, kd, amplitude)
                except Exception:
                    continue
                if not m.valid or m.rise_time_ms <= 0:
                    continue
                cost = (abs(m.overshoot_pct - target_overshoot)
                        + 0.03 * m.settling_time_ms + 0.02 * m.rise_time_ms)
                if best is None or cost < best[0]:
                    best = (cost, (kp, ki, kd), m)
    return best


def generate_simulation_training_data(n_samples: int = 120, seed: int = 42,
                                      val_split: float = 0.15) -> tuple:
    """闭环仿真标签：随机对象→网格搜最优 PID 作标签，物理可信度高于纯公式。

    较慢（每样本 ~90 次稳定仿真），n_samples 建议 100-300。
    Returns: (X_train, y_train, X_val, y_val)
    """
    from ..core.power_simulator import PlantModel, simulate_and_analyze
    rng = random.Random(seed)
    X, y = [], []
    for _ in range(n_samples):
        if rng.random() < 0.5:
            plant = PlantModel.first_order(K=rng.uniform(0.3, 2.5),
                                           T=rng.uniform(0.002, 0.05),
                                           L=rng.uniform(0.0, 0.005))
        else:
            plant = PlantModel.second_order(K=1.0, zeta=rng.uniform(0.15, 0.9),
                                            wn=rng.uniform(200, 2500))
        target = rng.choice([3, 5, 8, 10])
        best = _grid_best_pid(plant, target)
        if best is None:
            continue
        _, (bkp, bki, bkd), _bm = best
        # 当前参数：在最优附近扰动，得到"待优化"状态的实测指标
        ckp = max(0.0, bkp * rng.uniform(0.4, 1.6))
        cki = max(0.0, bki * rng.uniform(0.4, 1.6))
        ckd = max(0.0, bkd * rng.uniform(0.3, 2.0))
        try:
            cm = simulate_and_analyze(plant, ckp, cki, ckd, 1.0)
        except Exception:
            continue
        if not cm.valid:
            continue
        X.append([cm.overshoot_pct, cm.rise_time_ms, cm.settling_time_ms,
                  cm.steady_error_pct, ckp, cki, ckd, target])
        y.append([bkp, bki, bkd])

    n = len(X)
    n_val = int(n * val_split)
    idx = list(range(n))
    rng.shuffle(idx)
    vi = set(idx[:n_val])
    X_train = [X[i] for i in range(n) if i not in vi]
    y_train = [y[i] for i in range(n) if i not in vi]
    X_val = [X[i] for i in vi]
    y_val = [y[i] for i in vi]
    return X_train, y_train, X_val, y_val
