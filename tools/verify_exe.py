"""验证打包后的 PowerScope.exe —— 用应用自带的 --selftest 无头冒烟模式。

比"看进程有没有退出"强得多：
  - 确认 frozen 环境下能解压 _MEIPASS、枚举 profiles、加载 power_core.dll；
  - 逐 tab 截图，确认不是黑屏/白屏；
  - 输出 JSON 摘要（profile / 主题 / tab 数 / 变量数 / C 库可用性）。

用法:
    python tools/verify_exe.py [exe 路径] [输出目录]
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXE = os.path.join(ROOT, "dist_onefile", "PowerScope.exe")


def main() -> int:
    exe = sys.argv[1] if len(sys.argv) > 1 else EXE
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        os.environ.get("TEMP", "."), "exe_verify")
    os.makedirs(out, exist_ok=True)

    if not os.path.exists(exe):
        print(f"[FAIL] 找不到 {exe}")
        return 1

    print(f"EXE: {exe}")
    print(f"大小: {os.path.getsize(exe) / 1024 / 1024:.1f} MB")

    proc = subprocess.run(
        [exe, "--selftest", os.path.join(out, "shot.png")],
        capture_output=True, timeout=300)
    stdout = proc.stdout.decode("utf-8", errors="replace")
    stderr = proc.stderr.decode("utf-8", errors="replace")

    line = next((l for l in stdout.splitlines() if l.startswith("[selftest] ")), "")
    if not line:
        print("[FAIL] 没有拿到 selftest 摘要")
        print("stdout:", stdout[-2000:])
        print("stderr:", stderr[-2000:])
        return 1

    summary = json.loads(line[len("[selftest] "):])
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    shots = sorted(f for f in os.listdir(out) if f.endswith(".png"))
    print(f"\n截图 {len(shots)} 张 -> {out}")
    empty = [f for f in shots if os.path.getsize(os.path.join(out, f)) < 3000]
    if empty:
        print(f"[WARN] 疑似空白截图: {empty}")

    ok = (proc.returncode == 0
          and summary["c_core_dll_ok"]
          and summary["tabs"]
          and len(shots) >= len(summary["tabs"]) + 1)
    print("\n[PASS] 单文件 exe 冒烟测试通过" if ok else "\n[FAIL] 冒烟测试未通过")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
