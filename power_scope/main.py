"""PowerScope 应用入口"""
import sys
import os
from PySide6.QtWidgets import QApplication, QMessageBox
from .config.device_profile import load_profile, list_profiles
from .ui.power_main_window import PowerMainWindow


def _get_resource_dir():
    """获取资源目录 (支持 PyInstaller 打包环境)"""
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包后: 资源在 _MEIPASS 或 exe 同级目录
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _select_profile_path(profiles, argv):
    """显式参数优先；否则 NS800RT > 通用微逆 > 首个配置。"""
    if len(argv) > 1 and os.path.exists(argv[1]):
        return argv[1]
    for _ptype, path in profiles:
        if "ns800rt" in path.lower():
            return path
    for _ptype, path in profiles:
        lowered = path.lower()
        if "microinverter" in lowered or "micro" in lowered:
            return path
    return profiles[0][1]

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("PowerScope")
    app.setOrganizationName("PowerScope")

    # 列出可用设备配置
    profiles = list_profiles()
    if not profiles:
        QMessageBox.critical(None, "错误", "未找到任何设备配置文件。\n请将 .yaml 放入 profiles/ 目录")
        sys.exit(1)

    # 默认加载真机联调配置；命令行显式路径仍具有最高优先级
    profile_path = _select_profile_path(profiles, sys.argv)

    try:
        profile = load_profile(profile_path)
    except Exception as e:
        QMessageBox.critical(None, "配置加载失败", f"无法加载设备配置:\n{e}")
        sys.exit(1)

    window = PowerMainWindow(profile)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

