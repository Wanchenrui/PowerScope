"""
local_nn.py — 轻量级神经网络 PID 调参引擎 (纯 numpy 实现)

架构: MLP 8→32→16→3
  输入: [超调%, 上升时间ms, 调节时间ms, 稳态误差%, 当前Kp, 当前Ki, 当前Kd, 目标指标]
  隐藏: 32(ReLU) → 16(ReLU)
  输出: [新Kp, 新Ki, 新Kd] (线性)

特性:
  • 纯 numpy，无 PyTorch/TensorFlow 依赖
  • Adam 优化器 + He 初始化
  • 在线学习: 用户反馈后微调模型
  • 模型保存/加载 (JSON)
  • 训练数据来自控制理论仿真
"""
import json
import os
import math
import numpy as np
from datetime import datetime


class NeuralNetwork:
    """多层感知机 — numpy 实现"""

    def __init__(self, layer_sizes=None, learning_rate=0.001, seed=42):
        """
        Args:
            layer_sizes: [input, hidden1, hidden2, ..., output]
            learning_rate: 学习率
            seed: 随机种子，保证权重初始化与训练打乱可复现（None 则用全局 RNG）
        """
        self.layer_sizes = layer_sizes or [8, 32, 16, 3]
        self.lr = learning_rate
        self._rng = np.random.RandomState(seed) if seed is not None else np.random
        self.weights = []
        self.biases = []
        self._init_params()

        # Adam 优化器状态
        self.m_w = [np.zeros_like(w) for w in self.weights]
        self.v_w = [np.zeros_like(w) for w in self.weights]
        self.m_b = [np.zeros_like(b) for b in self.biases]
        self.v_b = [np.zeros_like(b) for b in self.biases]
        self.t = 0  # 时间步

        # 训练历史
        self.train_losses = []
        self.epochs_trained = 0

    def _init_params(self):
        """He 初始化 (适合 ReLU)"""
        for i in range(len(self.layer_sizes) - 1):
            fan_in = self.layer_sizes[i]
            std = math.sqrt(2.0 / fan_in)
            w = self._rng.randn(self.layer_sizes[i], self.layer_sizes[i + 1]) * std
            b = np.zeros((1, self.layer_sizes[i + 1]))
            self.weights.append(w)
            self.biases.append(b)

    def _relu(self, x):
        return np.maximum(0, x)

    def _relu_grad(self, x):
        return (x > 0).astype(float)

    def forward(self, X):
        """前向传播，返回输出和中间值 (用于反向传播)"""
        self.zs = []   # 线性输出
        self.as_ = [X]  # 激活输出
        a = X
        for i in range(len(self.weights)):
            z = a @ self.weights[i] + self.biases[i]
            self.zs.append(z)
            if i < len(self.weights) - 1:
                a = self._relu(z)
            else:
                a = z  # 输出层线性
            self.as_.append(a)
        return a

    def backward(self, X, y):
        """反向传播，返回梯度"""
        m = X.shape[0]
        grads_w = [None] * len(self.weights)
        grads_b = [None] * len(self.biases)

        # 输出层梯度 (MSE loss)
        delta = (self.as_[-1] - y) / m

        for i in reversed(range(len(self.weights))):
            grads_w[i] = self.as_[i].T @ delta
            grads_b[i] = np.sum(delta, axis=0, keepdims=True)
            if i > 0:
                delta = (delta @ self.weights[i].T) * self._relu_grad(self.zs[i - 1])

        return grads_w, grads_b

    def _adam_step(self, grads_w, grads_b, beta1=0.9, beta2=0.999, eps=1e-8):
        """Adam 优化器一步更新"""
        self.t += 1
        for i in range(len(self.weights)):
            self.m_w[i] = beta1 * self.m_w[i] + (1 - beta1) * grads_w[i]
            self.v_w[i] = beta2 * self.v_w[i] + (1 - beta2) * (grads_w[i] ** 2)
            m_hat = self.m_w[i] / (1 - beta1 ** self.t)
            v_hat = self.v_w[i] / (1 - beta2 ** self.t)
            self.weights[i] -= self.lr * m_hat / (np.sqrt(v_hat) + eps)

            self.m_b[i] = beta1 * self.m_b[i] + (1 - beta1) * grads_b[i]
            self.v_b[i] = beta2 * self.v_b[i] + (1 - beta2) * (grads_b[i] ** 2)
            m_hat_b = self.m_b[i] / (1 - beta1 ** self.t)
            v_hat_b = self.v_b[i] / (1 - beta2 ** self.t)
            self.biases[i] -= self.lr * m_hat_b / (np.sqrt(v_hat_b) + eps)

    def train(self, X, y, epochs=200, batch_size=32, verbose=False):
        """训练模型"""
        X = np.array(X, dtype=np.float64)
        y = np.array(y, dtype=np.float64)
        n = X.shape[0]

        for epoch in range(epochs):
            # 打乱数据
            idx = self._rng.permutation(n)
            X_shuf = X[idx]
            y_shuf = y[idx]

            epoch_loss = 0
            for start in range(0, n, batch_size):
                end = min(start + batch_size, n)
                Xb = X_shuf[start:end]
                yb = y_shuf[start:end]

                pred = self.forward(Xb)
                loss = np.mean((pred - yb) ** 2)
                epoch_loss += loss * (end - start)

                gw, gb = self.backward(Xb, yb)
                self._adam_step(gw, gb)

            epoch_loss /= n
            self.train_losses.append(epoch_loss)
            self.epochs_trained += 1

            if verbose and (epoch + 1) % 50 == 0:
                print(f"  Epoch {epoch+1}/{epochs}: loss={epoch_loss:.6f}")

        return self.train_losses[-1] if self.train_losses else 0

    def predict(self, X):
        """预测"""
        X = np.array(X, dtype=np.float64)
        if X.ndim == 1:
            X = X.reshape(1, -1)
        return self.forward(X)

    def online_learn(self, X, y, lr=None):
        """在线学习 — 单样本微调"""
        if lr:
            old_lr = self.lr
            self.lr = lr
        X = np.array(X, dtype=np.float64).reshape(1, -1)
        y = np.array(y, dtype=np.float64).reshape(1, -1)
        self.forward(X)
        gw, gb = self.backward(X, y)
        self._adam_step(gw, gb)
        if lr:
            self.lr = old_lr

    def save(self, path: str):
        """保存模型到 JSON"""
        model = {
            "layer_sizes": self.layer_sizes,
            "lr": self.lr,
            "weights": [w.tolist() for w in self.weights],
            "biases": [b.tolist() for b in self.biases],
            "epochs_trained": self.epochs_trained,
            "train_losses": self.train_losses[-100:],  # 只保留最近100个
            "saved_at": datetime.now().isoformat(),
        }
        with open(path, 'w') as f:
            json.dump(model, f)

    @classmethod
    def load(cls, path: str) -> "NeuralNetwork":
        """从 JSON 加载模型"""
        with open(path, 'r') as f:
            model = json.load(f)
        nn = cls(layer_sizes=model["layer_sizes"], learning_rate=model["lr"])
        nn.weights = [np.array(w) for w in model["weights"]]
        nn.biases = [np.array(b) for b in model["biases"]]
        nn.epochs_trained = model.get("epochs_trained", 0)
        nn.train_losses = model.get("train_losses", [])
        return nn


class PIDTunerNN:
    """PID 调参神经网络 — 封装特征工程和预测逻辑"""

    # 输入特征归一化范围
    INPUT_BOUNDS = [
        (0, 50),       # 超调 % (0-50)
        (1, 100),      # 上升时间 ms
        (5, 500),      # 调节时间 ms
        (0, 10),       # 稳态误差 %
        (0, 5),        # 当前 Kp
        (0, 2000),     # 当前 Ki
        (0, 0.5),      # 当前 Kd
        (0, 20),       # 目标超调 %
    ]

    # 输出归一化范围
    OUTPUT_BOUNDS = [
        (0, 5),        # Kp
        (0, 2000),     # Ki
        (0, 0.5),      # Kd
    ]

    def __init__(self, model_path: str = None):
        self.nn = NeuralNetwork([8, 32, 16, 3], learning_rate=0.001)
        self.model_path = model_path
        self._scaler = None
        self._val_loss = None  # 验证集残差(归一化MSE)，用于置信度校准

        if model_path and os.path.exists(model_path):
            try:
                self.nn = NeuralNetwork.load(model_path)
            except Exception:
                pass  # 加载失败用新模型

    def _normalize_input(self, features: list) -> np.ndarray:
        """归一化输入到 [0, 1]"""
        norm = []
        for i, (val, (lo, hi)) in enumerate(zip(features, self.INPUT_BOUNDS)):
            norm.append((val - lo) / (hi - lo))
        return np.array(norm, dtype=np.float64)

    def _denormalize_output(self, norm_output: np.ndarray) -> list:
        """反归一化输出"""
        result = []
        for i, (val, (lo, hi)) in enumerate(zip(norm_output[0], self.OUTPUT_BOUNDS)):
            result.append(lo + val * (hi - lo))
        return result

    def set_val_loss(self, val_loss):
        """设置验证集残差用于置信度校准。"""
        self._val_loss = val_loss

    def predict(self, overshoot: float, rise_time: float, settling_time: float,
                steady_error: float, current_kp: float, current_ki: float,
                current_kd: float, target_overshoot: float = 5.0) -> dict:
        """
        预测 PID 参数

        Returns:
            {"kp": float, "ki": float, "kd": float, "confidence": float}
        """
        features = [overshoot, rise_time, settling_time, steady_error,
                    current_kp, current_ki, current_kd, target_overshoot]
        X = self._normalize_input(features)
        y_norm = self.nn.predict(X)
        kp, ki, kd = self._denormalize_output(y_norm)

        # 安全限幅
        kp = max(0, min(5, kp))
        ki = max(0, min(2000, ki))
        kd = max(0, min(0.5, kd))

        # 置信度：优先用验证集残差校准，否则回退到训练量估计
        if self._val_loss is not None:
            import math as _m
            confidence = max(0.1, min(0.95, 0.95 - 2.5 * _m.sqrt(max(0.0, self._val_loss))))
        else:
            confidence = min(0.95, 0.3 + self.nn.epochs_trained * 0.002)

        return {"kp": kp, "ki": ki, "kd": kd, "confidence": confidence}

    def train_on_data(self, X_list: list, y_list: list, epochs=200, verbose=False):
        """用数据训练模型"""
        X_norm = np.array([self._normalize_input(x) for x in X_list])
        y_norm = np.array([[(v - lo) / (hi - lo) for v, (lo, hi) in zip(y, self.OUTPUT_BOUNDS)]
                           for y in y_list])
        return self.nn.train(X_norm, y_norm, epochs=epochs, verbose=verbose)

    def evaluate(self, X_list: list, y_list: list) -> float:
        """评估模型在给定数据上的 MSE 损失

        Args:
            X_list: 输入特征列表
            y_list: 目标输出列表

        Returns:
            float — 归一化空间的均方误差
        """
        X_norm = np.array([self._normalize_input(x) for x in X_list])
        y_norm = np.array([[(v - lo) / (hi - lo) for v, (lo, hi) in zip(y, self.OUTPUT_BOUNDS)]
                           for y in y_list])
        pred = self.nn.predict(X_norm)
        return float(np.mean((pred - y_norm) ** 2))

    def online_learn(self, features: list, target_params: list, lr=0.01):
        """在线学习 — 用户反馈后微调"""
        X = self._normalize_input(features)
        y = np.array([(v - lo) / (hi - lo) for v, (lo, hi) in zip(target_params, self.OUTPUT_BOUNDS)])
        self.nn.online_learn(X, y, lr=lr)
        if self.model_path:
            self.nn.save(self.model_path)

    def save(self, path: str = None):
        path = path or self.model_path
        if path:
            self.nn.save(path)

    @property
    def is_trained(self) -> bool:
        return self.nn.epochs_trained > 0

    @property
    def epochs(self) -> int:
        return self.nn.epochs_trained
