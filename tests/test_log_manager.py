"""test_log_manager.py — 日志系统测试"""
import pytest
import tempfile
import os
from power_scope.core.log_manager import LogManager


class TestLogManager:
    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """重置单例避免交叉污染"""
        LogManager._instance = None
        yield
        LogManager._instance = None

    def test_singleton(self):
        l1 = LogManager()
        l2 = LogManager()
        assert l1 is l2

    def test_log_levels(self, caplog):
        """测试各级日志输出"""
        import logging
        log = LogManager()
        with caplog.at_level(logging.DEBUG):
            log.debug("debug msg")
            log.info("info msg")
            log.warning("warning msg")
            log.error("error msg")
        assert "debug msg" in caplog.text
        assert "info msg" in caplog.text
        assert "warning msg" in caplog.text
        assert "error msg" in caplog.text

    def test_log_path(self):
        log = LogManager()
        path = log.get_log_path()
        assert "power_scope" in str(path).lower()
        assert str(path).endswith(".log")

    def test_clear_logs(self):
        log = LogManager()
        log.clear_logs()
        path = log.get_log_path()
        if path.exists():
            assert path.read_text() == ""
