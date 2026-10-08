"""settings.py — 配置持久化 (QSettings)

封装 QSettings，提供类型安全的读写接口。

使用方式:
    from .settings import AppSettings
    settings = AppSettings()
    port = settings.serial_port()  # 读取上次使用的串口
    settings.set_serial_port("COM3")  # 保存当前串口
"""
from __future__ import annotations
from PySide6.QtCore import QSettings


class AppSettings:
    """应用配置持久化"""

    _instance: AppSettings | None = None

    def __new__(cls) -> AppSettings:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._settings = QSettings("PowerScope", "PowerScope")
        return cls._instance

    # ------------------------------------------------------------------
    # 串口配置
    # ------------------------------------------------------------------

    def serial_port(self) -> str:
        return self._settings.value("serial/port", "", type=str)

    def set_serial_port(self, port: str) -> None:
        self._settings.setValue("serial/port", port)

    def serial_baudrate(self) -> int:
        return self._settings.value("serial/baudrate", 115200, type=int)

    def set_serial_baudrate(self, baudrate: int) -> None:
        self._settings.setValue("serial/baudrate", baudrate)

    # ------------------------------------------------------------------
    # 主题
    # ------------------------------------------------------------------

    def theme(self) -> str:
        return self._settings.value("ui/theme", "dark", type=str)

    def set_theme(self, theme: str) -> None:
        self._settings.setValue("ui/theme", theme)

    def theme_explicit(self) -> bool:
        """用户是否显式切换过主题。

        没有这个标志就无法区分「从未设置」和「用户选了 dark」，
        会导致 settings 里的默认 dark 覆盖 profile 的 solar 默认值。
        """
        return self._settings.value("ui/theme_explicit", False, type=bool)

    def set_theme_explicit(self, value: bool = True) -> None:
        self._settings.setValue("ui/theme_explicit", bool(value))

    # ------------------------------------------------------------------
    # 串口帧配置（端口 + 波特率 + 数据位 + 校验 + 停止位）
    # ------------------------------------------------------------------

    #: 界面下拉框文本 ↔ pyserial 参数
    PARITY_TEXT = {"None": "N", "Even": "E", "Odd": "O", "Mark": "M", "Space": "S"}
    PARITY_REVERSE = {v: k for k, v in PARITY_TEXT.items()}

    def serial_frame(self) -> dict:
        """上次成功连接的串口帧配置（无记录时返回空 dict）。"""
        raw = self._settings.value("serial/frame", "", type=str)
        if not raw:
            return {}
        out = {}
        for part in raw.split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                out[k] = v
        return out

    def set_serial_frame(self, frame: dict) -> None:
        raw = ";".join(f"{k}={v}" for k, v in frame.items())
        self._settings.setValue("serial/frame", raw)
        # 兼容旧 API
        if frame.get("port"):
            self.set_serial_port(frame["port"])
        if frame.get("baudrate"):
            try:
                self.set_serial_baudrate(int(frame["baudrate"]))
            except (TypeError, ValueError):
                pass

    # ------------------------------------------------------------------
    # 界面状态
    # ------------------------------------------------------------------

    def active_tab(self) -> int:
        return self._settings.value("ui/active_tab", 0, type=int)

    def set_active_tab(self, index: int) -> None:
        self._settings.setValue("ui/active_tab", int(index))

    def nav_collapsed(self) -> bool:
        return self._settings.value("ui/nav_collapsed", False, type=bool)

    def set_nav_collapsed(self, value: bool) -> None:
        self._settings.setValue("ui/nav_collapsed", bool(value))

    # ------------------------------------------------------------------
    # 工作区（P1-7：开机是否恢复上次工作区）
    # ------------------------------------------------------------------

    def restore_workspace(self) -> bool:
        """开机是否自动恢复上次工作区（默认开启）。"""
        return self._settings.value("ui/restore_workspace", True, type=bool)

    def set_restore_workspace(self, value: bool) -> None:
        self._settings.setValue("ui/restore_workspace", bool(value))

    # ------------------------------------------------------------------
    # 最近文件
    # ------------------------------------------------------------------

    def recent_elf_files(self) -> list[str]:
        """最近使用的 ELF 文件列表 (最多 5 个)"""
        return self._settings.value("files/recent_elf", [], type=list)

    def add_recent_elf(self, path: str) -> None:
        """添加 ELF 文件到最近列表"""
        recent = self.recent_elf_files()
        if path in recent:
            recent.remove(path)
        recent.insert(0, path)
        self._settings.setValue("files/recent_elf", recent[:5])

    def recent_profiles(self) -> list[str]:
        """最近使用的设备配置文件列表"""
        return self._settings.value("files/recent_profiles", [], type=list)

    def add_recent_profile(self, path: str) -> None:
        recent = self.recent_profiles()
        if path in recent:
            recent.remove(path)
        recent.insert(0, path)
        self._settings.setValue("files/recent_profiles", recent[:5])

    # ------------------------------------------------------------------
    # 窗口状态
    # ------------------------------------------------------------------

    def window_size(self) -> tuple[int, int]:
        w = self._settings.value("window/width", 1280, type=int)
        h = self._settings.value("window/height", 800, type=int)
        return (w, h)

    def set_window_size(self, width: int, height: int) -> None:
        self._settings.setValue("window/width", width)
        self._settings.setValue("window/height", height)

    # ------------------------------------------------------------------
    # LLM 配置
    # ------------------------------------------------------------------

    def llm_provider(self) -> str:
        return self._settings.value("llm/provider", "neural", type=str)

    def set_llm_provider(self, provider: str) -> None:
        self._settings.setValue("llm/provider", provider)

    def llm_api_key(self) -> str:
        """⚠ 明文存储，生产环境应使用 keyring 等加密方案"""
        return self._settings.value("llm/api_key", "", type=str)

    def set_llm_api_key(self, key: str) -> None:
        self._settings.setValue("llm/api_key", key)

    # ------------------------------------------------------------------
    # 调参
    # ------------------------------------------------------------------

    def tuning_loop_type(self) -> str:
        return self._settings.value("tuning/loop_type", "电流内环 (d轴)", type=str)

    def set_tuning_loop_type(self, loop: str) -> None:
        self._settings.setValue("tuning/loop_type", loop)

    def tuning_method(self) -> str:
        return self._settings.value("tuning/method", "IMC 内模控制法", type=str)

    def set_tuning_method(self, method: str) -> None:
        self._settings.setValue("tuning/method", method)
