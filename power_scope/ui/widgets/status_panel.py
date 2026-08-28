"""状态面板组件 — LED 指示灯矩阵"""
from PySide6.QtWidgets import QFrame, QVBoxLayout, QGridLayout, QHBoxLayout, QLabel, QWidget
from .gauge import LedIndicator


class StatusPanelWidget(QFrame):
    """状态指示面板 — 多 LED 指示灯网格"""

    def __init__(self, title, indicators, profile):
        super().__init__()
        self.setObjectName("card")
        self._profile = profile
        self._leds = {}
        lay = QVBoxLayout(self)
        lbl = QLabel(title)
        lbl.setObjectName("title")
        lay.addWidget(lbl)
        grid = QGridLayout()
        grid.setSpacing(8)
        for i, iid in enumerate(indicators):
            idef = next((s for s in profile.status_indicators if s.id == iid), None)
            if not idef:
                continue
            cell = QHBoxLayout()
            led = LedIndicator(idef.color_on, idef.color_off)
            l = QLabel(idef.label)
            # font-size via QSS
            cell.addWidget(led)
            cell.addWidget(l)
            cell.addStretch()
            cw = QWidget()
            cw.setLayout(cell)
            grid.addWidget(cw, i // 4, i % 4)
            self._leds[iid] = (led, idef)
        lay.addLayout(grid)
        lay.addStretch()

    def update_values(self, values):
        for iid, (led, idef) in self._leds.items():
            v = values.get(idef.var)
            if v is not None:
                led.set_on(v == idef.on_value)
