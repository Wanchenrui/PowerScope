"""test_settings.py — 配置持久化测试"""
import pytest
import tempfile
import os
from PySide6.QtCore import QSettings
from power_scope.core.settings import AppSettings


class TestAppSettings:
    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """每个测试重置单例并清除设置，避免配置交叉污染"""
        AppSettings._instance = None
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        s = AppSettings()
        s._settings.clear()  # 清除所有持久化数据
        yield
        AppSettings._instance = None

    def test_singleton(self):
        s1 = AppSettings()
        s2 = AppSettings()
        assert s1 is s2

    def test_serial_port(self):
        s = AppSettings()
        assert s.serial_port() == ""
        s.set_serial_port("COM3")
        assert s.serial_port() == "COM3"

    def test_serial_baudrate(self):
        s = AppSettings()
        assert s.serial_baudrate() == 115200
        s.set_serial_baudrate(921600)
        assert s.serial_baudrate() == 921600

    def test_theme(self):
        s = AppSettings()
        assert s.theme() == "dark"
        s.set_theme("light")
        assert s.theme() == "light"

    def test_recent_elf(self):
        s = AppSettings()
        assert s.recent_elf_files() == []
        s.add_recent_elf("/path/to/file1.elf")
        s.add_recent_elf("/path/to/file2.elf")
        recent = s.recent_elf_files()
        assert len(recent) == 2
        assert recent[0] == "/path/to/file2.elf"

    def test_recent_elf_limit(self):
        s = AppSettings()
        for i in range(10):
            s.add_recent_elf(f"/path/to/file{i}.elf")
        recent = s.recent_elf_files()
        assert len(recent) == 5
        assert recent[0] == "/path/to/file9.elf"

    def test_recent_elf_dedup(self):
        s = AppSettings()
        s.add_recent_elf("/path/to/file.elf")
        s.add_recent_elf("/path/to/other.elf")
        s.add_recent_elf("/path/to/file.elf")  # 重复
        recent = s.recent_elf_files()
        assert len(recent) == 2
        assert recent[0] == "/path/to/file.elf"

    def test_window_size(self):
        s = AppSettings()
        assert s.window_size() == (1280, 800)
        s.set_window_size(1920, 1080)
        assert s.window_size() == (1920, 1080)

    def test_llm_provider(self):
        s = AppSettings()
        assert s.llm_provider() == "neural"
        s.set_llm_provider("deepseek")
        assert s.llm_provider() == "deepseek"

    def test_llm_api_key(self):
        s = AppSettings()
        assert s.llm_api_key() == ""
        s.set_llm_api_key("sk-test-key")
        assert s.llm_api_key() == "sk-test-key"

    def test_tuning_loop_type(self):
        s = AppSettings()
        assert s.tuning_loop_type() == "电流内环 (d轴)"
        s.set_tuning_loop_type("电压外环")
        assert s.tuning_loop_type() == "电压外环"

    def test_tuning_method(self):
        s = AppSettings()
        assert s.tuning_method() == "IMC 内模控制法"
        s.set_tuning_method("Ziegler-Nichols")
        assert s.tuning_method() == "Ziegler-Nichols"
