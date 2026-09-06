# T09 固件参数运行约束交接

最终状态：CODE_VERIFIED / BENCH_PENDING；command_t06 独审通过，统一全套 888 passed / exit0、无 skip。提交组合见 [B2协调](b2-coordination.md)，独审见 [review-b2-t09.md](review-b2-t09.md)。以下未提交/待审等为实现交接时记录。
未提交、推送、串口连接、烧录或带电运行。PC 真实控制仍默认拒绝。

## 范围与依据

PC 基线 `7fcd8d7740bbe4d5378b9eb87ab901d838de002c`；FW 唯一可改树
`D:/GitHub/PowerScope/build/fw-t03`，分支 `plan/t03-protocol-identity`，
HEAD `9a5c50cea54ef063f84a5837e3fbb17ca59d2a11`。读取两份 planning、B1 协调、
T03/T05 交接及 T03 独审后实施。原 `D:/GitHub/newns800RT50xx` clean，旧 ELF
SHA256 仍 `80b8ba7c699df7316c1e5d084bd37112e36c589bd9c7d90cd94fea47c0d9f9ec`。

FW 仅改 `debug_monitor_core.c/.h`、`uart_msg_port.c`，新增私有窄实现头
`debug_parameter_write_impl.h`。PC 仅改原 `tests/firmware_ns5039/test_core.c`，
新增 `t09_state_fixture.h`、`t09_driver.c`、`tests/test_t09_firmware.py` 和本文。
未改构建脚本、冻结线格式、九项 ACL 条目/上下界、功率算法、保护/PWM 阈值、PI 注释
或控制静态库。review_driver.c/test_t03_review.py 留给独审者维护。

实际时序依据：bsp_task.c 的 STIM3_Isr 调调度器，TASK_1msProcess 调 UART_Task1ms；
TASK_5msProcess 只递增请求，BSP_TASK_ProcessDeferred 在主循环调 FSM_Process。
因此真实调试写在 STIM3 低优先级 ISR 任务，并非普通主线程。bsp_fsm.c 中
BSP_FSM_Stop 只置 turnOnOff=OFF，FSM 仍可能为 RUN/SHUTDOWN；
BSP_FSM_DisableRunModules 分别关闭参数消费者并提交 PWM 禁用。

## 设备规则与观测接口

WRITE_MEM 和 SET_PARAM 共同走既有 ACL/长度/有限值/范围检查。九项真实 float
仅在以下条件同时满足时提交：FSM=IDLE、turnOnOff=TURN_OFF，无 faultLatched、
shutdownRequest、hwProtectWait、PROTECT 锁存；HAL protection event 仅 NONE/CMD；
电流、电压、RMS、INV_MUX 状态均为 STATE_DISABLE；PWM 软件状态恰为
HAL_PWM_DRV_DISABLE 且没有 drvEnablePend。故障/未知 protection event 返回既有
PROTECTED=6，其余未停机状态返回既有 BUSY=5。未知状态按拒绝处理。

scratch 保留独立小范围写规则，运行/故障不会单独阻止 scratch，不意味着真实参数获权。
真实参数只写一个对齐 float。临界区先保存 PRIMASK，再关中断，复核实际对象并写单个
标量，最后恢复原 PRIMASK；不无条件开启中断，不在区间内编码/发送响应或复制大缓冲。
最终 ARM 反汇编证实受理分支是单条 32 位 STR，见 build/t09-write-disassembly.log。
实际源码测试使用同一私有实现头，未用可控 mock 返回值替代判定。

ACK 内容和长度不变：DEVICE_CONTROL 成功回显仍只是所受理的命令，不能作为实际停机
字段。新 ELF 观测符号 `g_dm_control_observation` 为 48 字节、12 个连续 uint32：
generation、fsm_state、turn_on_off、fault_latched、shutdown_request、hw_protect_wait、
protection_latched、protection_event、loop_enable_mask、pwm_drive_state、
pwm_enable_pending、parameter_write_status。loop mask 位 0..3 为电流/电压/RMS/MUX。
parameter_write_status 是当前状态对真实参数的许可结果，非最后命令完成结果。
独立 `g_dm_last_write_status` 是最近 WRITE_MEM/SET_PARAM 的实际软件响应状态，
包括 ACL/有限值拒绝和 scratch 结果。既有 FSM、保护和参数符号仍可读。

UART 每次 1ms 任务及真实参数尝试时刷新观测。全部字段在短屏蔽中断区间采集，
generation 更新前为奇数、完成后为偶数（uint32 回绕）。PC 应使用匹配 ELF/身份，
单次 ReadMemory 读完整 48 字节；分多次读取则前后 generation 必须相等且为偶数。
同 STIM3 的完整 ReadMemory 不会与快照更新重入。初始化 status=BUSY，刷新前不授权。
最终构建中 observation 地址 0x20001520、last_write_status 地址 0x200006f8；
地址只适用于下面精确构建，不作为硬编码 PC 常量。

观测是软件状态，不是物理 PWM/电压证据。FSM 静态库未导出内部转态进度；公开
START/SHUTDOWN/ON/pending/使能状态均拒绝，但不承诺主循环恢复后持续停机。
当前安全约束是写入瞬间消费者全禁用、检查和单标量提交不被普通 ISR 打断；没有在线
多参数事务或未来状态锁。NMI/物理保护行为与真实 40kHz 时序预算尚未台架验证。
Debug watchdog 仍仅停数据流，测试明确保留 RUN 状态且后续参数写拒绝。

## 实测与产物

PowerShell：

```powershell
./scripts/ns5039-test-host.ps1 -Firmware build/fw-t03 -Compiler build/toolchain/bin/gcc.exe
$env:POWERSCOPE_TEST_FW='D:/GitHub/PowerScope/build/fw-t03'
$env:POWERSCOPE_TEST_HOST_CC='D:/GitHub/PowerScope/build/toolchain/bin/gcc.exe'
.venv/Scripts/python.exe -m pytest tests/test_t09_firmware.py -q -s -p no:cacheprovider
.venv/Scripts/python.exe scripts/ns5039-build-target.py --fw build/fw-t03 --cc build/t03-arm-toolchain/arm-gnu-toolchain-12.3.rel1-mingw-w64-i686-arm-none-eabi/bin/arm-none-eabi-gcc.exe --make build/toolchain/bin/mingw32-make.exe --out build/t09-identity-final-v2
```

2026-09-06：旧实际 C **229 checks / exit0**（build/t09-host.log）；
T09 实际 C **474 checks**、Python **1 passed in 0.32s / exit0，无 skip**
（build/t09-runtime.log）。覆盖九项两写命令停机成功；INIT/START/RUN/SHUTDOWN/未知
状态、ON、各故障标志、各保护 event、四个消费者、PWM 启动待决/未知状态；scratch
正向、非白名单、NaN/正负 Inf、原已关中断/开中断恢复，以及 watchdog 停流不等于停机。
测试 count 和 pytest count 范围重叠，不相加。原 host warning 仍仅 unused totalBytes。

最终官方 Arm GNU 12.3.Rel1 全量编译、链接、objcopy、manifest **exit0**，日志
`build/t09-target-final-v2.log`；text/data/bss=126284/8836/157524。
342 项当前源 hash 全匹配构建记录，dirty=true，如实绑定上述 PC/FW 基线。
未改静态库 SHA256 `35b2b7bc5f5a30b757a97519f7c781ddaead7364a4772f1381db41ea9998b48e`。
`git -C build/fw-t03 diff --check` exit0。

最终目录 `build/t09-identity-final-v2`：

- build ID：`5145f8a1f726c7c0daf94044928dd90ecb6d6ac180a52fa4da275c5109841c7a`
- manifest SHA256：`b7b83b05d5d5623f35b93a32dbe2534bdf9002c07b190f41cc56c7912eeb5270`
- ELF SHA256：`6853e2705fbe95a99f01f68f22e2277b1df6a5a84a02847ccf6c8a72ee5d51eb`
- BIN SHA256：`bdb4424177fc87dd7a1230cb6eefca301df237c32a468eeb4bdf8b82b96703aa`

B1 原 powerscope-out 和生成头完整备份到 `build/t09-b1-preserved`；移动前核实绝对
源/目标均在专属 build 内，单 PowerShell 操作，无原 Debug 写入。首轮目标构建也成功，
但新增行 CRLF 触发 diff-check，修复仅新增行末后完整重建 v2；首轮保留
`build/t09-target-first`、`build/t09-identity-final` 和 `build/t09-target-final.log`，
不能作为最终源身份。当前 FW powerscope-out/生成头为 v2 产物，不提交。

未跑 PC 全套，不自作最终独审。真实板上身份、读回、物理 PWM、ISR 时间、故障到停机
时延及功率算法效果仍 BENCH_PENDING。生产现冻结供独审，生产修复仍由本实现者负责。
