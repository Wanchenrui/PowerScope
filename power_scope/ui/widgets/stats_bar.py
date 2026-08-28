"""状态条组件 — 实时显示连接 / 吞吐 / 帧 / CRC 统计

数据来源 DebugService.stats_snapshot()。颜色全部走主题语义类（#dim / role），
不写死字面色，切主题自动适配。
"""
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel


class StatsBarWidget(QWidget):
    """放入 QStatusBar 的常驻统计条"""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 0, 8, 0)
        lay.setSpacing(14)
        self._conn = QLabel("○ 未连接")
        self._rate = QLabel("RX 0 B/s")
        self._frames = QLabel("帧 0")
        self._crc = QLabel("CRC错 0")
        self._vars = QLabel("更新 0")
        for w in (self._conn, self._rate, self._frames, self._crc, self._vars):
            w.setObjectName("dim")
            lay.addWidget(w)

    def update_stats(self, snapshot, connected=False, rate_bps=0):
        """用统计快照刷新各字段。snapshot: DebugService.stats_snapshot() 的 dict"""
        self._conn.setText("● 已连接" if connected else "○ 未连接")
        self._set_role(self._conn, "ok" if connected else "dim")
        self._rate.setText(f"RX {self._fmt_rate(rate_bps)}")
        self._frames.setText(f"帧 {snapshot.get('frames_ok', 0)}")
        crc = snapshot.get("crc_errors", 0)
        self._crc.setText(f"CRC错 {crc}")
        self._set_role(self._crc, "err" if crc else "dim")
        self._vars.setText(f"更新 {snapshot.get('var_updates', 0)}")

    def _set_role(self, w, role):
        """切换语义角色并重新应用样式（不写死颜色）"""
        if role == "dim":
            w.setObjectName("dim")
            w.setProperty("role", None)
        else:
            w.setObjectName("")
            w.setProperty("role", role)
        w.style().unpolish(w)
        w.style().polish(w)

    @staticmethod
    def _fmt_rate(bps):
        if bps >= 1024:
            return f"{bps / 1024:.1f} KB/s"
        return f"{int(bps)} B/s"
