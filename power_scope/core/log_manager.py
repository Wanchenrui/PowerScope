"""log_manager.py — 分级日志系统

替代 QMessageBox/statusBar 的输出方式，提供分级日志：
- DEBUG: 详细调试信息
- INFO: 一般操作信息
- WARNING: 警告
- ERROR: 错误

使用方式:
    from .log_manager import LogManager
    log = LogManager()
    log.info("设备已连接")
    log.warning("串口数据超时")
    log.error("协议解析失败: %s", reason)
"""
from __future__ import annotations
import logging
import sys
from pathlib import Path
from typing import Optional


class LogManager:
    """分级日志管理器 — 单例"""

    _instance: LogManager | None = None

    def __new__(cls) -> LogManager:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_logger()
        return cls._instance

    def _init_logger(self) -> None:
        """初始化 logger 和 handler"""
        self._logger = logging.getLogger("PowerScope")
        self._logger.setLevel(logging.DEBUG)

        # 避免重复添加 handler
        if self._logger.handlers:
            return

        # 控制台输出
        console = logging.StreamHandler(sys.stderr)
        console.setLevel(logging.INFO)
        fmt = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%H:%M:%S"
        )
        console.setFormatter(fmt)
        self._logger.addHandler(console)

        # 文件输出
        log_dir = Path.home() / ".power_scope" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(
            log_dir / "power_scope.log",
            encoding="utf-8"
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(fmt)
        self._logger.addHandler(file_handler)

    # ------------------------------------------------------------------
    # 分级日志接口
    # ------------------------------------------------------------------

    def debug(self, msg: str, *args) -> None:
        self._logger.debug(msg, *args)

    def info(self, msg: str, *args) -> None:
        self._logger.info(msg, *args)

    def warning(self, msg: str, *args) -> None:
        self._logger.warning(msg, *args)

    def error(self, msg: str, *args) -> None:
        self._logger.error(msg, *args)

    def critical(self, msg: str, *args) -> None:
        self._logger.critical(msg, *args)

    # ------------------------------------------------------------------
    # 日志文件管理
    # ------------------------------------------------------------------

    def get_log_path(self) -> Path:
        return Path.home() / ".power_scope" / "logs" / "power_scope.log"

    def clear_logs(self) -> None:
        """清空日志文件"""
        path = self.get_log_path()
        if path.exists():
            path.write_text("")
