"""app_paths.py — 用户数据目录解析

持久化数据（会话录制 DB、快捷命令、工作区快照、写入审计）必须落在
「当前用户可写」的位置，而不是 exe 同级目录（Program Files / 只读介质
下会静默失败）：

  - frozen: %APPDATA%\\PowerScope（exe 同级 WriteAttempt 目录仅作旧数据兼容）
  - 源码运行: <项目根>/ .powerscope_data（不污染仓库上层，即项目根目录下）

统一走 data_dir()；测试可用环境变量 POWERSCOPE_DATA_DIR 指向临时目录。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def data_dir() -> Path:
    """返回可写的用户数据目录（不存在则创建）。"""
    override = os.environ.get("POWERSCOPE_DATA_DIR")
    if override:
        base = Path(override)
    elif getattr(sys, "frozen", False):
        base = Path(os.environ.get("APPDATA", str(Path.home()))) / "PowerScope"
    else:
        # 源码运行：项目根（本文件的上两级）
        base = Path(__file__).resolve().parent.parent.parent / ".powerscope_data"
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError:
        # 极端只读环境：退回当前目录，保证功能降级可用而非崩溃
        base = Path.cwd()
    return base


def user_file(name: str) -> Path:
    """用户数据目录下的文件路径。"""
    return data_dir() / name
