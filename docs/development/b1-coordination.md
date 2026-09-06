# B1 协调与集成记录

2026-09-06，承接 `cdfc83029c0233e4fea30b59f474c99a50612a03`。

本轮范围为 T03、T04 剩余部分与 T05。G0/T04-A 的历史验收见
[review-g0.md](review-g0.md)；本轮新改动不沿用旧审查结论。协调 agent
只负责规划、文件归属、审查与集成，实际实现由 GPT-6 Astra Medium 子 agent 完成。
同时最多三个执行或审查子 agent，最终审查者必须与该任务实现者不同。

## 起点核对

- PC 工作区及远端 `plan/g0-reliability-foundation` 均为 `cdfc830`，开始时 clean。
- FW 原工作区 `D:/GitHub/newns800RT50xx` 为 `3469da8eaeb2b5657381df49817e350f35964c15`，开始时 clean。
- 现存 ELF SHA-256：`80b8ba7c699df7316c1e5d084bd37112e36c589bd9c7d90cd94fea47c0d9f9ec`。
- 控制静态库 SHA-256：`35b2b7bc5f5a30b757a97519f7c781ddaead7364a4772f1381db41ea9998b48e`。
- G0 日志实存且尾部为 724 passed in 25.45s；这是历史结果，不是 B1 验收。

## 文件归属与依赖

| 实现者 | 独占范围 | 交接约束 |
|---|---|---|
| firmware_t03 | 独立 FW 工作树的真实 Debug C/头文件、构建身份与链接段、真实 C 路径测试；PC 新增 NS5039 专属脚本/夹具及 t03-handoff | `uart_msg_port.c` 如需修改先预约；manifest 生成与 schema 由本任务唯一维护 |
| session_t04 | Session、DebugService、MsgService、必要 transport/protocol 适配、对应测试及 t04-handoff | main_window 先仅做生命周期接入，释放后交 T05；variable_inspector 仅预约读取分块接入；共享 contracts 变更先协调 |
| catalog_t05 | DeviceProfile、NS/ESS 配置、ELF 描述、DevicePack、manifest 核验、目录测试与 t05-handoff | power_main_window 最小目录适配；main_window 等 T04 释放；消费 T03 的 manifest schema |
| 协调 agent | 本文、全局依赖与验收记录 | 不编写业务实现或代替实现者修复 |

FW 工作树计划为 `build/fw-t03`，分支 `plan/t03-protocol-identity`；原 FW
checkout 及现存构建物保持原状。PC 在当前项目分支共享工作区，按上表串行交接重叠文件。
每项实现交付后再分配独立审查文件，审查者只读被审生产文件，问题回交实现者。

最终独立审查配对：catalog_t05 审 T03，firmware_t03 审 T04，session_t04 审 T05。
PC 全套集成测试等文件冻结后由单一执行者运行，避免共享工作区中的并发全套结果被误当成最终快照。

已协调接口：Session 管理 epoch、identity、capabilities 与失效信号；身份核验回传必须
匹配当前 epoch/build ID。Debug 单帧上限与高层分块读取分开，实际读取入口消费分块接口。
manifest 由 T03 生成、T05 核验，要求本地 ELF 的 `.powerscope_build_id` 实际节与
设备 ID 一致；未目标构建的记录不得标为 `BUILT`。

## 本轮放行条件

1. T03 的 181/182/192/193、16/17、64/超 64、CRC/截断/越界等测试执行实际固件 C 处理路径。主机 HAL 接缝、目标 ARM 构建、真实串口与台架分别记录。
2. PSC1 扩展保持冻结偏移和旧前缀；真实 C 输出可由 PC 解析。manifest/build ID 无循环依赖，dirty 输入可追溯，设备与构建物不匹配保持受限。
3. T04 清理旧请求、解析和布局代次；命令、序号和长度匹配。旧 MSG 超时后不能以静默等待或重开串口证明 ACK 可重新配对。
4. T05 的 resolved/readable/ACL/effect/tunable 独立；18 项中 8 项 ACL、10 项拒绝写，未启用电流 PI 不可整定。未知类型/身份/库版本不授权，换 ELF/profile 使旧缓存失效，ESS 独立。
5. 各实现专项通过且独立审查阻断关闭后，执行集成回归，再提交和推送项目分支。T06 以后不计入本轮完成范围。

真实控制继续受 G0 默认拒绝约束。未经真实硬件验证的项目始终为
`BENCH_PENDING`；ARM 工具链缺失或目标链接失败另记构建待验，不能由主机 C 或 Mock 通过覆盖。

## 最终软件验收

T03、T04 与 T05 的本轮代码范围均已独立审查，未关闭阻断为零。审查记录：
[T03](review-b1-t03.md)、[T04](review-b1-t04.md)、[T05](review-b1-t05.md)。
实现者与最终审查者仍按上表分离；所有生产修复均回交原实现者。

独审发现并关闭了零有效采样周期 ACK 提交、未知版本数据分发、MSG 控制 opcode
伪装只读，以及排队旧 ELF 事件跨 profile/窗口污染。后者用实际 QWidget 事件链复现，
修复采用加载来源与代次绑定；`event_bus.py` 的 `ElfLoadedEvent.load_token` 和检查器
加载事件已按预约交给 T05。新增条件表达式也按审查要求简化，没有扩展控制 ACL 或算法。

统一全套由 session_t04 单独执行。首轮为 **766 passed / 8 failed / exit1**，日志
`build/b1-first-pytest.log`；八项旧夹具缺少新契约前置或新增字段断言，最小迁移由原
实现者完成，原行为断言保留，分别经独立审查复核。第二轮为 **774 passed in 44.89s /
exit0，无 skip**，日志 `build/b1-final-pytest.log`；生产文件在第二轮前冻结。

可复跑命令（工具链和 FW 路径为本机此次输入，可替换为相应显式路径）：

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
$env:POWERSCOPE_TEST_ELF = 'D:/GitHub/newns800RT50xx/Debug/C01_2in1_20260821_ongridStable.elf'
$env:POWERSCOPE_TEST_FW = 'D:/GitHub/PowerScope/build/fw-t03'
$env:POWERSCOPE_TEST_HOST_CC = 'D:/GitHub/PowerScope/build/toolchain/bin/gcc.exe'
./.venv/Scripts/python.exe -c "from PySide6.QtWidgets import QApplication; app=QApplication([]); import pytest; raise SystemExit(pytest.main(['tests','-q','--tb=short','-p','no:cacheprovider']))"
```

此外实际固件 C 处理路径 **229 checks 通过**，独立真实 C 向量 **12 项通过**；这些
计数与 Python 全套存在范围重叠，不相加。已下载并校验官方 Arm GNU 12.3.Rel1 到本地
隔离目录，实际全量 ARM 编译、链接及 manifest 生成通过；text/data/bss 为
125900/8784/157524 字节。目标构建步骤、警告与校验值见 [T03 交接](t03-handoff.md)。

## 交付组合与剩余边界

| 项目 | 本轮固定记录 |
|---|---|
| PC | `plan/g0-reliability-foundation`，`cdfc830` 后的本文所属 B1 集成提交 |
| FW | `plan/t03-protocol-identity`，`9a5c50cea54ef063f84a5837e3fbb17ca59d2a11` |
| DevicePack | `ns5039-v1` / schema 1；ESS 为独立 `ess-observation-v1` 观测模板 |
| 构建 ID | `ba046c174342118e27927c5eb4af73a051853d66799a9e96e3593a677db48fd8` |
| manifest SHA-256 | `3738e8ff3ab53de66f774c393c28a60da9748a11befb4537c3deb77eb5ff44c6` |
| 新 ELF SHA-256 | `5df210946d5780a999bc1f35c4ed5c84193ba716c9d1f9317f2b63b6b9cdd38d` |
| 新 BIN SHA-256 | `f555c0c0ab9f3faf1069289b24ca3772a03fcbb46c88ee7fe17f57e83c690d5b` |

产物在 `build/t03-identity-final`。构建发生于提交前，manifest 如实保留 PC `cdfc830`、
FW `3469da8` 和 `dirty=true`；341 项源码输入及完整快照记录该次真实构建，审查已确认
最终源码内容一致。上述 FW 提交承载这组源码，不把提交后的编号回填成已经执行过的新构建。
ELF 内嵌 ID、完整 Flash BIN、库、快照与 PC 核验器均已离线交叉核验；使用的 ID 输入
来自本地构建物，**不是实读板上 ID**。生成身份头、工具链、目标产物与日志不提交。

真实串口、板上身份、升级、DMA/时序与功率效果均保持 `BENCH_PENDING`；G1 尚未放行。
真实控制仍默认拒绝。无线上启动代次时，同 build 重启不能可靠自动识别；Debug 序号
在服务生命周期不复用，65535 耗尽拒绝继续；旧 MSG 不确定命令不会因重连自动恢复。
完整升级编排留 T13，真实控制和结果确认继续依赖 T06/T07/T08/T09 及台架。

下批可按依赖派 T06（唯一命令服务）、T09（固件运行约束）和 T10（数据块）；维持文件
归属及独立审查，不能因本轮离线通过开放真实控制。T03/T04/T05 实现文件已释放。
