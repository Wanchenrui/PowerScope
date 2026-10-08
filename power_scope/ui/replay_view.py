"""replay_view.py — 会话录制回放视图（P1-10「时光机」）

core/session_recorder.py 早已把 var/updated 事件落 SQLite，本视图补上
「时间轴回放界面」：选会话 → 勾变量 → 播放倍速 → 曲线按录制时刻重放。

数据量控制：单变量预载上限 200k 点（超出截断并提示），回放按时间轴
分片喂给 RealtimePlotWidget —— 不从头到尾一次性 setData，避免大会话卡死。

导出：选中变量合并导出 CSV（时间戳 + 每变量一列）。
"""
from __future__ import annotations

import csv
import time as _time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QFileDialog, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QProgressBar, QPushButton, QSlider,
    QSplitter, QVBoxLayout, QWidget,
)

from .theme import spacing, ui_color
from .widgets.empty_state import EmptyState
from .widgets.icon_button import IconButton
from .widgets.realtime_plot import RealtimePlotWidget

#: 单变量预载上限（超出截断，避免超大会话拖垮 UI）
_PRELOAD_CAP = 200_000

_SPEEDS = (1, 4, 16, 64)


class SessionReplayView(QWidget):
    """会话回放：session 列表 + 变量选择 + 时间轴播放。"""

    replay_status = Signal(str)

    def __init__(self, recorder=None, parent=None):
        super().__init__(parent)
        from ..core.session_recorder import SessionRecorder
        from ..core.app_paths import user_file
        self._recorder = recorder or SessionRecorder(
            str(user_file("sessions.db")))
        self._sessions: list[dict] = []
        self._session_id: int | None = None
        self._series: dict[str, tuple[list[float], list[float]]] = {}
        self._replay_upto: dict[str, int] = {}   # 每变量已渲染到的时间戳下标
        self._extent: tuple[float, float] | None = None
        self._playing = False
        self._speed_index = 0
        self._cursor = 0.0
        self._build()
        self._refresh_sessions()

    # ---- UI ----
    def _build(self):
        root = QVBoxLayout(self)
        splitter = QSplitter(Qt.Horizontal)

        left = QWidget()
        left.setMinimumWidth(240)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(spacing("sm"))
        ll.addWidget(QLabel("会话（SessionRecorder 录制）"))
        self._session_list = QListWidget()
        self._session_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._session_list.currentRowChanged.connect(self._on_session_changed)
        ll.addWidget(self._session_list, 1)
        ll.addWidget(QLabel("变量（双击勾选）"))
        self._var_list = QListWidget()
        self._var_list.setSelectionMode(QAbstractItemView.NoSelection)
        self._var_list.itemChanged.connect(self._on_var_toggled)
        ll.addWidget(self._var_list, 2)
        self._session_stats = QLabel("")
        self._session_stats.setObjectName("dim")
        self._session_stats.setWordWrap(True)
        ll.addWidget(self._session_stats)
        splitter.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(spacing("sm"))

        self._plot = RealtimePlotWidget(time_window=30.0)
        rl.addWidget(self._plot, 1)

        bar = QHBoxLayout()
        bar.setSpacing(spacing("sm"))
        self._play_btn = IconButton("play", "播放", tooltip="按录制时刻回放")
        self._play_btn.setCheckable(True)
        self._play_btn.toggled.connect(self._on_play_toggled)
        bar.addWidget(self._play_btn)
        self._speed_btn = IconButton("trigger", f"{_SPEEDS[0]}x",
                                     tooltip="回放倍速")
        self._speed_btn.clicked.connect(self._cycle_speed)
        bar.addWidget(self._speed_btn)
        self._timeline = QSlider(Qt.Horizontal)
        self._timeline.setEnabled(False)
        self._timeline.sliderMoved.connect(self._on_timeline_moved)
        bar.addWidget(self._timeline, 1)
        self._clock = QLabel("--:--")
        self._clock.setObjectName("dim")
        bar.addWidget(self._clock)
        export_btn = IconButton("export", "导出CSV", tooltip="导出选中变量")
        export_btn.clicked.connect(self._on_export)
        bar.addWidget(export_btn)
        rl.addLayout(bar)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(3)
        rl.addWidget(self._progress)

        self._empty = EmptyState(
            "replay", "还没有录制会话",
            "连接设备后由调试流程驱动；此处按时间轴回放录制的变量曲线")
        self._stack_placeholder = self._empty
        right.layout().addWidget(self._empty)

        splitter.addWidget(right)
        splitter.setSizes([300, 700])
        root.addWidget(splitter)

        # 回放定时器：每个 tick 按倍速推进时间轴
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._on_tick)

    # ---- 会话数据 ----
    def _refresh_sessions(self):
        self._sessions = self._recorder.list_sessions()
        self._session_list.clear()
        for session in self._sessions:
            stamp = _time.strftime("%m-%d %H:%M",
                                   _time.localtime(session["created_at"]))
            label = f"{stamp}  {session['name']}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, session)
            self._session_list.addItem(item)
        self._session_stats.setText(f"{len(self._sessions)} 个会话")

    def _on_session_changed(self, row: int):
        if row < 0 or row >= len(self._sessions):
            return
        self._stop_playback()
        session = self._sessions[row]
        self._session_id = session["id"]
        stats = self._recorder.get_stats(session["id"])
        self._session_stats.setText(
            f"{session['name']} | {session.get('device_name') or ''}\n"
            f"记录 {stats.get('total_records', 0)} 点")
        names = self._recorder.get_var_names(session["id"])
        self._var_list.clear()
        for name in names:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self._var_list.addItem(item)
        self._series.clear()
        self._extent = self._load_session_extent(session["id"])
        self._setup_timeline()
        self._plot.clear_data()
        self._plot.clear_channels()
        self._plot_stack_switch(True)
        self._empty.set_description(
            f"已选会话「{session['name']}」，勾选左侧变量开始回放")

    def _load_session_extent(self, session_id: int):
        stats = self._recorder.get_stats(session_id)
        start = stats.get("start_time")
        end = stats.get("end_time")
        if start is None or end is None or end <= start:
            return None
        return (float(start), float(end))

    def _setup_timeline(self):
        if self._extent is None:
            self._timeline.setEnabled(False)
            return
        start, end = self._extent
        self._timeline.setEnabled(True)
        self._timeline.setRange(0, max(1, int((end - start) * 1000)))
        self._timeline.setValue(0)
        self._clock.setText(_time.strftime(
            "%H:%M:%S", _time.localtime(start)))

    def _plot_stack_switch(self, show_empty: bool):
        # 复用一个显隐开关，避免为单组件引入 QStackedWidget
        self._empty.setVisible(show_empty)

    # ---- 变量勾选 → 预载 ----
    def _on_var_toggled(self, item: QListWidgetItem):
        if self._session_id is None:
            return
        name = item.text()
        if item.checkState() == Qt.Checked:
            if name in self._series:
                return
            times: list[float] = []
            values: list[float] = []
            for record in self._recorder.playback(name,
                                                  session_id=self._session_id):
                times.append(record.timestamp)
                values.append(record.phys_value)
                if len(times) >= _PRELOAD_CAP:
                    self.replay_status.emit(
                        f"⚠ {name} 超过 {_PRELOAD_CAP} 点，已截断")
                    break
            if not times:
                item.setCheckState(Qt.Unchecked)
                return
            self._series[name] = (times, values)
            self._replay_upto[name] = 0
            self._plot.add_channel(name)
            self.replay_status.emit(
                f"→ 已载入 {name}: {len(times)} 点")
        else:
            self._series.pop(name, None)
            self._replay_upto.pop(name, None)
            self._plot.remove_channel(name)
            self._empty.setVisible(not self._series)

    # ---- 播放控制 ----
    def _on_play_toggled(self, checked: bool):
        if checked:
            self._start_playback()
        else:
            self._pause_playback()

    def _start_playback(self):
        if not self._series or self._extent is None:
            self._play_btn.blockSignals(True)
            self._play_btn.setChecked(False)
            self._play_btn.blockSignals(False)
            self.replay_status.emit("⚠ 请先勾选至少一个变量")
            return
        self._playing = True
        if self._cursor <= self._extent[0]:
            self._cursor = self._extent[0]
        self._timer.start()
        self._empty.setVisible(False)

    def _pause_playback(self):
        self._playing = False
        self._timer.stop()

    def _stop_playback(self):
        self._pause_playback()
        self._cursor = self._extent[0] if self._extent else 0.0

    def _cycle_speed(self):
        self._speed_index = (self._speed_index + 1) % len(_SPEEDS)
        speed = _SPEEDS[self._speed_index]
        self._speed_btn.setText(f"{speed}x")
        self.replay_status.emit(f"→ 回放倍速 {speed}x")

    def _on_timeline_moved(self, value: int):
        if self._extent is None:
            return
        start = self._extent[0]
        self._cursor = start + value / 1000.0
        self._render_upto(self._cursor)

    def _on_tick(self):
        if not self._playing or self._extent is None:
            return
        start, end = self._extent
        speed = _SPEEDS[self._speed_index]
        # 50ms tick × 倍速：把 1s 会话压缩到 50ms/speed 放完
        self._cursor += 0.05 * speed
        if self._cursor >= end:
            self._cursor = end
            self._play_btn.blockSignals(True)
            self._play_btn.setChecked(False)
            self._play_btn.blockSignals(False)
            self._playing = False
            self._timer.stop()
            self.replay_status.emit("✓ 回放结束")
        self._render_upto(self._cursor)
        self._timeline.blockSignals(True)
        self._timeline.setValue(int((self._cursor - start) * 1000))
        self._timeline.blockSignals(False)
        span = max(1e-9, end - start)
        self._progress.setValue(int(100 * (self._cursor - start) / span))

    def _render_upto(self, cursor: float):
        """把 cursor 之前的新样本喂进绘图（增量，不做全量重绘）。"""
        for name, (times, values) in self._series.items():
            # 二分找最后一个 ≤ cursor 的下标
            lo, hi = -1, len(times) - 1
            while hi - lo > 1:
                mid = (lo + hi) // 2
                if times[mid] <= cursor:
                    lo = mid
                else:
                    hi = mid
            upto = lo
            rendered = self._replay_upto.get(name, 0)
            if upto >= rendered:
                for index in range(rendered, upto + 1):
                    self._plot.add_sample(name, times[index], values[index])
                self._replay_upto[name] = upto + 1
        self._clock.setText(_time.strftime(
            "%H:%M:%S", _time.localtime(cursor)))

    # ---- 导出 ----
    def _on_export(self):
        if not self._series:
            self.replay_status.emit("⚠ 没有可导出的变量")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出回放数据", "replay.csv", "CSV (*.csv)")
        if not path:
            return
        try:
            names = list(self._series.keys())
            # 汇合全部时间戳（排序去重），每行写「该时刻各变量最新值」
            stamps = sorted({t for times, _v in self._series.values()
                             for t in times})
            merged: dict[str, float] = {}
            cursors = {name: 0 for name in names}
            with open(path, "w", newline="", encoding="utf-8") as stream:
                writer = csv.writer(stream)
                writer.writerow(["timestamp"] + names)
                for stamp in stamps:
                    for name in names:
                        times, values = self._series[name]
                        while (cursors[name] < len(times)
                               and times[cursors[name]] <= stamp):
                            merged[name] = values[cursors[name]]
                            cursors[name] += 1
                    writer.writerow([f"{stamp:.6f}"]
                                    + [f"{merged.get(n, '')}" for n in names])
            self.replay_status.emit(
                f"✓ 已导出 {len(stamps)} 行 × {len(names)} 变量 → {path}")
        except OSError as exc:
            self.replay_status.emit(f"✗ 导出失败: {exc}")

    # ---- 清理 ----
    def cleanup(self):
        self._stop_playback()
        try:
            self._recorder.close()
        except Exception:
            pass
