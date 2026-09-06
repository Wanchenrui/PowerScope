# Windows 本地开发环境（T00，2026-09-06）

**B1 更新：** 后续 T03 已在隔离目录使用匹配的官方 Arm GNU 12.3.Rel1 完成真实目标
重建，原 FW checkout 与现存 ELF 未覆盖。统一全套现为 774 passed / exit0，无 skip。
复跑命令及构建物见 [B1 协调记录](b1-coordination.md) 和 [T03 交接](t03-handoff.md)。
下文 724 项及“未找到 ARM 工具链”保留为 T00 当时的历史结果，台架仍待验。

验证组合为 Windows x64、CPython 3.12.14、Qt/PySide6 6.11.2、NumPy 2.5.2、pytest 9.1.1。`requirements.txt` 只含运行依赖，`requirements-dev.txt` 增加测试依赖；`requirements-dev-lock.txt` 固定本次验证的完整开发依赖版本。未承诺 Python 3.14 或 Linux/macOS 支持。

## 从干净环境执行

提供 Python 3.12 和 Windows x64 MinGW GCC 的可执行路径；脚本不修改全局 Python、不自动下载工具。

```powershell
./scripts/setup-environment.ps1 -Python C:/path/to/python.exe
./scripts/build-native.ps1 -Compiler C:/path/to/mingw64/bin/gcc.exe -Install
$env:QT_QPA_PLATFORM = 'offscreen'
./.venv/Scripts/python.exe -m pytest tests -q --tb=short -p no:cacheprovider
```

native 编译输出在 `build/native`；`-Install` 明确复制两份 DLL 到项目根目录，供现有加载器及集成测试使用。未加此参数时只构建和运行 C 单元测试，不更新根目录 DLL。脚本编译生产 C 源、通用 MCU 测试桩、四个 C 测试程序和 ABI 探针，任何编译或测试非零退出立即停止。运行 `tests/test_native_abi.py` 比较实际 C 头文件的大小/偏移与 ctypes 结构，并验证加载器全部必需导出可绑定、CRC 黄金向量正确。

本机原 GCC 安装路径含中文，链接器无法解析 CRT 路径；只读复制工具链到忽略目录 `build/toolchain` 后可正常使用。目录 junction 不能解决该 GCC 的路径规范化问题。通用脚本不假定此个人工具位置；使用 ASCII 工具链路径即可。已验证 GCC 16.2.0（MinGW-W64 x86_64-ucrt-posix-seh）。现成编译器可用，未下载新工具；备选官方分发说明为 [LLVM-MinGW](https://github.com/mstorsjo/llvm-mingw)，未将备选当作已验证工具链。

DLL 仅依赖 Windows kernel/UCRT，无额外 libgcc DLL 依赖。ctypes 为 64 位指针，C `uint32_t` 为 4 字节；编译探针覆盖 Modbus request/response 和 Debug frame。`modbus_codec.c` 有一处既有有符号比较警告，本次未更改业务行为。

## 外部固件测试输入

不再隐式访问开发者绝对路径。四项需要外部 ELF 的测试使用共享 `firmware_elf` fixture：没有配置时明确 skip；显式配置不存在时失败；文件存在时运行所有原业务断言，不因解析失败而跳过。

```powershell
$env:POWERSCOPE_TEST_ELF = 'D:/path/to/C01_2in1_20260821_ongridStable.elf'
./.venv/Scripts/python.exe -m pytest tests/test_msg_elf.py tests/test_ns800rt_tuning_profile.py tests/test_profile_elf_autoload.py -q
```

固定地址 oracle 已绑定 ELF SHA-256，见 `tests/fixtures/c01_20260821_addresses.json`。独立 Q 审查直接使用 pyelftools 的符号表根地址与 DWARF 成员偏移核实 18 字段，未调用被测 ELFParser；fixture 保存来源和偏移。未知哈希仅跳过固定地址测试，其余解析、类型和加载测试照跑。旧 oracle 的 `0x2000208C` 未有匹配旧 ELF 哈希证据，不再套用于当前 ELF。

## 已执行结果与边界

PC 原基线 `e2ce8ab` 用 `git archive` 导出至忽略目录 `build/baseline-source`，复用隔离解释器及已构建的 DLL，避开并行开发文件变动。原选定 14 文件 **178 passed / exit 0**（`build/selected-baseline.log`）；原全套 **670 passed、4 failed / exit 1**（`build/full-baseline.log`），四项失败均为原有个人 ELF 路径缺失。

中途共享开发快照全套曾为 **688 passed、11 failed / exit 1**（`build/full-current.log`），处于 T02 实现过程中；随后首轮集成为720 passed/4 failed，剩余模拟授权夹具和用户NN缓存隔离问题已修复并独立审查。上述失败是保留的历史，不是最终状态。

2026-09-06协调 agent 最终统一全套验收：**724 passed in 25.45s / exit0，无skip**，日志`build/final-pytest-verified.log`；设置`QT_QPA_PLATFORM=offscreen`、`POWERSCOPE_TEST_ELF`显式指向下文SHA256为80b8...的现存ELF。环境专项最终 **8 passed / exit0**（`build/environment-tests.log`）；native C测试 **34/34 passed / exit0**（CRC6、Debug11、Modbus9、RingBuffer8），构建日志`build/native-build.log`；`pip check`及`git diff --check`退出0。G0与T04-A当前代码范围已验收，独立证据与边界见[审查记录](review-g0.md)。日志和构建物均不提交；此结果不包含ARM目标重建、真实串口或台架验证。

本次两 DLL 的 SHA-256（PE 构建时间戳可能导致复编译哈希变化；不宣称逐字节可复现）：

| 文件 | SHA-256 |
|---|---|
| power_core.dll | `8cc0363cd6fe975778f21c56bc623c428772c11b98c76e7efc5609bb0d8c1894` |
| mock_mcu.dll | `3b52da46fac4427f5c456e6317f2cfd3e4df799bcbac48ecbd9e3da679afd8ce` |

native 加载器仍在导入时绑定 DLL；缺失时明确报“无法找到…请确保已编译”。纯离线分析基线不依赖它，但加载 UI/native 调用模块前仍须构建安装 DLL。延迟加载策略未在本任务擅自改变，未来若需要无 native 的 UI 应另行处理。

## 目标固件只读清点

FW 工作区 `D:/GitHub/newns800RT50xx`，提交 `3469da8eaeb2b5657381df49817e350f35964c15`，清点时 tracked/untracked 状态均 clean。现存 ELF SHA-256 为 `80b8ba7c699df7316c1e5d084bd37112e36c589bd9c7d90cd94fea47c0d9f9ec`；预编译 `cbb/libcbb_minv_2in1.a` 为 `35b2b7bc5f5a30b757a97519f7c781ddaead7364a4772f1381db41ea9998b48e`。

`Debug/makefile` 使用 `arm-none-eabi-gcc`，Cortex-M7/ARMv7E-M、hard-float、fpv5-d16，链接 `ns800rt5039_eflash.ld` 和该预编译库。存在生成 makefile、map、ELF，但 PATH 和本机 C:/、D:/ 文件名清点均未发现 ARM GCC，故 **目标重建未执行**，现存 ELF 不视为重建证据。本轮未改 FW 文件、未覆盖构建物。获得匹配 ARM 工具链后应先在隔离工作树重建，记录链接 map、内存占用、库哈希和编译器版本。

GUI 测试使用 offscreen，不等同桌面交互验收；通用 `mock_mcu.dll` 不等同真实 NS5039 固件。串口、升级、硬件时序及带电台架均为 **BENCH_PENDING**。
