"""PowerScope 根级入口脚本 — 供 PyInstaller 打包和直接运行使用"""
import sys
import os

# 确保项目根目录在 Python 路径中
_project_root = os.path.dirname(os.path.abspath(__file__))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from power_scope.main import main

if __name__ == "__main__":
    sys.exit(main())
