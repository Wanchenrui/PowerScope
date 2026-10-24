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
        self._crc = QLabel("CRC 0")
        self._vars = QLabel("更新 0")
        self._conn.setObjectName("dim")
        for w in (self._rate, self._frames, self._crc, self._vars):
            w.setObjectName("stat_value")
        self._conn.setToolTip("当前设备连接状态")
        self._rate.setToolTip("每秒接收字节数")
        self._frames.setToolTip("成功解析的协议帧数量")
        self._crc.setToolTip("CRC 校验错误数量；出现错误时需要检查通信链路")
        self._vars.setToolTip("收到的变量更新总数")
        for w in (self._conn, self._rate, self._frames, self._crc, self._vars):
            lay.addWidget(w)

    def update_stats(self, snapshot, connected=False, rate_bps=0):
        """用统计快照刷新各字段。snapshot: DebugService.stats_snapshot() 的 dict"""
        self._set_text(self._conn, "● 已连接" if connected else "○ 未连接")
        self._set_role(self._conn, "ok" if connected else "dim")
        self._set_text(self._rate, f"RX {self._fmt_rate(rate_bps)}")
        self._set_text(self._frames, f"帧 {snapshot.get('frames_ok', 0)}")
        crc = snapshot.get("crc_errors", 0)
        self._set_text(self._crc, f"CRC {crc}")
        self._set_role(self._crc, "err" if crc else "dim")
        self._set_text(self._vars, f"更新 {snapshot.get('var_updates', 0)}")

    @staticmethod
    def _set_text(widget, text):
        if widget.text() != text:
            widget.setText(text)

    def _set_role(self, w, role):
        if w.property("role") == role:
            return
        object_name = "dim" if role == "dim" else "stat_value"
        if w.objectName() != object_name:
            w.setObjectName(object_name)
        w.setProperty("role", role)
        w.style().unpolish(w)
        w.style().polish(w)
        w.update()

    @staticmethod
    def _fmt_rate(bps):
        if bps >= 1024:
            return f"{bps / 1024:.1f} KB/s"
        return f"{int(bps)} B/s"
