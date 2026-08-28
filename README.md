# PowerScope — 光伏微逆与储能串口调试仿真平台

## 快速开始

### 运行打包版 (无需 Python 环境)

```
dist/PowerScope/PowerScope.exe    ← 双击运行
```

### 开发环境运行

```bash
pip install PySide6 pyelftools pyserial cffi pyyaml pytest
# 编译 C 核心库
tcc -shared -o power_core.dll -Ipower_core/include power_core/src/*.c
# 启动
python -m power_scope.main
```

### 运行测试

```bash
# C 单元测试 (需 TCC 编译器)
tcc -o test.exe -Ipower_core/include power_core/tests/test_crc16.c power_core/src/crc16_table.c && test.exe

# Python 测试
python -m pytest tests/ -v
```

## 工程目录结构

```
UARTproject/
├── power_core/                    # C 核心库 (高性能热路径)
│   ├── include/                   #   头文件 (CFFI 接口定义)
│   │   ├── power_core.h
│   │   ├── crc16_table.h          #   CRC16-Modbus
│   │   ├── ring_buffer.h          #   环形缓冲区
│   │   ├── modbus_codec.h         #   Modbus RTU 编解码
│   │   └── debug_protocol.h       #   调试协议引擎
│   ├── src/                       #   C 实现
│   └── tests/                     #   C 单元测试 (43项)
│
├── mcu_debug_stub/                # MCU 端调试桩 (可移植到固件)
│   ├── debug_monitor.h            #   接口定义
│   ├── debug_monitor.c            #   核心逻辑 (平台无关)
│   ├── port/                      #   移植示例
│   │   └── stm32_hal_port.c       #     STM32 HAL 移植
│   └── tests/                     #   调试桩测试 (9项)
│
├── power_scope/                   # Python 应用 (UI + 业务逻辑)
│   ├── __init__.py
│   ├── main.py                    #   应用入口
│   ├── core/                      #   核心服务层
│   │   └── cffi_loader.py         #     CFFI/ctypes 桥接 C 库
│   ├── config/                    #   配置系统
│   │   └── device_profile.py      #     YAML 设备配置加载
│   ├── debug/                     #   调试模块
│   │   └── elf_parser.py          #     ELF/DWARF 解析
│   ├── ui/                        #   UI 层 (PySide6)
│   │   ├── main_window.py         #     主窗口 + 配置驱动界面
│   │   └── theme.py               #     主题系统 (dark/light/solar)
│   └── profiles/                  #   设备配置文件
│       ├── microinverter.yaml     #     微逆变器 (开机/关机/清除故障)
│       └── ess_storage.yaml       #     储能系统 (并网/离网/充电/放电/VSG)
│
├── tests/                         # Python 测试 (101项)
│   ├── test_cffi_bridge.py        #   CFFI 桥接测试
│   ├── test_elf_parser.py         #   ELF 解析测试
│   ├── test_device_config.py      #   设备配置测试
│   ├── test_integration_e2e.py    #   端到端集成测试
│   ├── test_stress_perf.py        #   性能压力测试
│   ├── test_boundary_edge.py      #   边界值测试
│   ├── test_modbus_full.py        #   Modbus 全功能码测试
│   ├── test_real_scenario.py      #   真实场景模拟
│   ├── cross_verify_crc16.py      #   C/Python 交叉验证
│   ├── cross_verify_modbus.py     #   C/Python 交叉验证
│   └── mock_mcu.c                 #   模拟 MCU DLL 源码
│
├── docs/                          # 文档
│   ├── user_guide.md              #   完整使用指南
│   ├── mcu_debug_and_elf_design.md#   MCU交互与ELF解析设计
│   ├── comprehensive_test_report.md#  测试报告
│   └── integration_test_report.md #   集成测试报告
│
├── dist/                          # 打包产物
│   └── PowerScope/
│       ├── PowerScope.exe         #   可执行文件 (5.4MB)
│       └── _internal/             #   依赖库 + DLL + 配置
│
├── concept-images/                # UI 概念图
│   ├── 01_serial_monitor_main.png
│   ├── 02_dual_mode_tuning_panel.png
│   ├── 03_realtime_oscilloscope.png
│   └── 04_plugin_architecture.png
│
├── power_core.dll                 # 编译的 C 核心库
├── mock_mcu.dll                   # 模拟 MCU (测试用)
├── PowerScope_调研报告与实施方案.docx
├── research_and_implementation.md # 调研报告
└── README.md                      # 本文件
```

## 测试覆盖

| 类别 | 数量 |
|------|:----:|
| C 单元测试 | 43 |
| Python 集成测试 | 101 |
| **总计** | **144** |

## 技术栈

| 层级 | 技术 |
|------|------|
| C 核心 | TCC/GCC 编译, CFFI/ctypes 桥接 |
| Python 业务 | PySide6 (Qt6), pyelftools, pyserial |
| 配置 | YAML 设备配置文件 |
| 打包 | PyInstaller |
