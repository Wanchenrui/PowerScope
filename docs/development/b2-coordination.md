# B2 协调与集成记录

2026-09-06，承接已验收 B1。主 agent 只负责规划、文件归属、审查和集成记录；
实现由三个 GPT-6 Astra Medium 子 agent 执行，独审占用同一并发额度。
本轮范围仅 T06 / T09 / T10；T07 / T08 / T11 留给 B3。

## 起点与证据

- PC：`plan/g0-reliability-foundation`，`7fcd8d7740bbe4d5378b9eb87ab901d838de002c`，起点 clean。
- FW：`build/fw-t03`，`plan/t03-protocol-identity`，`9a5c50cea54ef063f84a5837e3fbb17ca59d2a11`。
- FW 未跟踪的 `powerscope-out/` 和 `user/include/powerscope_build_id.h` 为 B1 构建物，保留且不提交。
- 原 FW checkout `D:/GitHub/newns800RT50xx` 仍为 `main` / `3469da8`，起点 clean，只读。
- B1 的 774 Python、229 真实 C 检查和 ARM 构建属于历史验收，不能替代本批最终验证。
- 两个远端分支经 `ls-remote` 核对与上述 HEAD 一致。首次直连 GitHub 443 失败；
  使用系统已配置的本地代理作单条 git 命令参数后成功，未更改全局 git/系统配置。

输入已核对两份规划、[B1 协调](b1-coordination.md)、任务及 T03/T04/T05 交接、
`review-b1-*`。T06 依赖 T03/T04/T05，T09 依赖 T03/T05，T10 依赖 T01/T04，
当前软件依赖已满足。硬件门槛仍未满足。

## 文件归属

| 实现者 | 独占范围 | 共享接口约束 |
|---|---|---|
| command_t06 | CommandService / 编码器、Guardrails、DebugService、MsgService、Session；T06 专项与交接 | 不改 UI；T10 所需 Debug 接缝由本实现者按约定接入 |
| firmware_t09 | FW Debug core / UART 窄 FSM 接口及头；实际 C 实现 harness、T09 专项与交接 | 不扩大 ACL，不改功率算法、保护阈值或静态库；独审 driver 保留给审查者 |
| data_t10 | EventBus、StreamingManager、Wave 数据适配、新块队列、contracts；T10 专项/基准与交接 | contracts 唯一维护者；新增共享字段先通知消费方；不改 UI 或 DebugService |
| 主 agent | 本文、依赖和验收汇总 | 不写业务实现，不代替实现者修复 |

公共 conftest、构建脚本、未列文件须预约。每个文件仅一名写入者；独审只读生产，
发现问题回交原实现者。计划最终独审配对：data_t10 审 T06、command_t06 审 T09、
firmware_t09 审 T10。冻结生产并关闭独审阻断后，指定单一执行者运行全套。

已协调接口：T10 唯一维护 SampleBlock 的兼容默认字段 `quality_flags`、
`first_sample_id`、`layout_generation`，新增 sample_pipeline / sample_queue；
Debug 实际解码接入由 T06 写入。T06 复用已有 Intent/Receipt/Observation，审计记录
置于 CommandRecord，不另建共享命令契约。实际 FW 的 0x0C/0x0D ACK 为一字节回显，
PC 原成功长度约束需按实物纠正；这仍只代表 ACK，不能表示状态生效。

## 放行条件

1. T06 校验与编码拒绝路径、ACK/回读/实际效果分离、截止时间与失效、部分完成均有独立反例；无真实控制授权旁路。
2. T09 对现有系数执行明确停机约束，scratch 单列；实际 C 处理路径与目标 ARM 构建分别验证；命令 ACK 不代表 PWM 已停。
3. T10 原始类型、时间与质量保留，有界消费者队列及可见丢弃计数；换布局/epoch 不混旧数据；基准不冒充串口吞吐。
4. 独审及最终软件测试通过后分别提交、推送两个对应项目分支，记录确切兼容组合和构建身份。

真实控制继续默认拒绝，硬件项目保持 `BENCH_PENDING`。本批软件完成也不构成 G1 放行。

## 实现与审查过程（历史）

T06 / T09 / T10 已提交实现交接，进入交叉 CODE_REVIEW。T06 相关专项 110 项通过；
T09 229 项原真实 C 检查及 474 项运行约束检查通过，最终源已全量 ARM 重建；
T10 相关专项 70 项通过并完成固定离线基准。这些是实现验证，非本批最终验收。

根审查已回交实现者处理：设备控制 ACK 实际长度、参数描述等待期间换址、
状态源异常默认拒绝、Live 序号与每通道样本 ID、跨流缺口归属、Qt detached
flush 失效及双解析高频事件副本。T06 接缝曾出现明确 NACK 后旧布局不再解码的
回归（104 passed / 1 failed），保留原业务断言，按明确拒绝语义恢复旧 ACK 布局。

独立 T10 首轮另复现两项阻断：慢流序号 65535→1 漏报 seq0 缺失、消费者丢弃把
原 INVALID 样本降成 GAP。已回交 data_t10；审查者保留反例，待最终修复复核。
后续独审还复现丢样位置回贴较早块、未知总缺样被写成精确数量，以及 Live 同组第二
通道误判重复。根协调此前按“全局逐帧序号”指导修改的判断不准确，已撤回：真实
`Dm_PrepareLiveBlock` 每组递增且跳过 0，`Dm_BuildLiveFrame` 对组内各通道回显同一
序号；慢 stream 和 Recorder 的 uint16 序号均包含 0。最终实现/测试必须以此真实
C 语义为准。必要时 SampleBlock 可兼容追加 `consumer_dropped_samples=0`，设备总
缺样未知仍保留 None，不增加多层丢样框架。
最终全套、独审放行和提交组合待实际完成后记录。

## 最终独立审查

三项软件审查阻断均已关闭，生产与测试已冻结：

- T06：data_t10 独审，22 个独立反例及相关专项共 132 passed / exit0。
  整数缩放先转 float 的精度问题由 command_t06 改为精确有理数转换并独立复核。
- T09：command_t06 独审，41 passed / exit0；真实 C 状态门禁、临界区竞态、
  原 PRIMASK 恢复、ARM 单标量写以及 342 源输入/manifest 实物核验通过。
- T10：firmware_t09 独审，17 个独立反例及相关专项共 87 passed / exit0。
  上述序号、质量放宽、丢样位置和未知计数问题均由原实现者修复并保留反例。

计数范围互有重叠，不相加。最终记录分别见 [T06](review-b2-t06.md)、
[T09](review-b2-t09.md)、[T10](review-b2-t10.md)。command_t06 是唯一全套执行者。

## 最终软件验收

生产及测试冻结后，command_t06 统一执行 **888 passed in 49.06s / exit0，无 skip**。
日志 `build/b2-final-pytest.log`，退出码 `build/b2-final-pytest.exit`。`pip check`
返回 No broken requirements / exit0；双仓库 `git diff --check` exit0。本次全套
没有失败或夹具迁移；过程中的专项失败保留在对应审查记录。

```powershell
$env:QT_QPA_PLATFORM='offscreen'
$env:POWERSCOPE_TEST_ELF='D:/GitHub/newns800RT50xx/Debug/C01_2in1_20260821_ongridStable.elf'
$env:POWERSCOPE_TEST_FW='D:/GitHub/PowerScope/build/fw-t03'
$env:POWERSCOPE_TEST_HOST_CC='D:/GitHub/PowerScope/build/toolchain/bin/gcc.exe'
.venv/Scripts/python.exe -c "from PySide6.QtWidgets import QApplication; app=QApplication([]); import pytest; raise SystemExit(pytest.main(['tests','-q','--tb=short','-p','no:cacheprovider']))"
```

T06 / T09 / T10 本批软件范围状态为 **CODE_VERIFIED / BENCH_PENDING**，实现与
最终审查分离。真实固件 C 的原 229 项和新增运行策略 474 项分别通过，ARM 全量构建
及独立实物交叉核验通过；与 Python 计数重叠，不合成一个总数。

末版 T10 固定离线基准：10000 预建帧，送入 9897 帧，103 次故意缺帧全部识别；
plot 峰值 25680 字节且无丢块，recorder 峰值 8387088 字节、丢弃 4998 块 /
159936 样本有计数。wall 3.467 秒，CPU 3.344 秒，RSS 采样峰值 52690944 字节。
这不是 GUI 绘制、真实串口或台架吞吐测试；30 分钟/2 小时验证仍属 T12/T18 后续。

## 构建组合与剩余边界

T09 最终真实 ARM 产物为 `build/t09-identity-final-v2`，text/data/bss 为
126284/8836/157524 字节，官方 Arm GNU 12.3.Rel1 完整编译/链接/objcopy/manifest
exit0。独审已核对完整 ELF/BIN、静态库、ELF 内嵌 ID 及 dirty 源快照。

| 项目 | 固定记录 |
|---|---|
| PC | `plan/g0-reliability-foundation`，本文所属 B2 集成提交 |
| FW | `plan/t03-protocol-identity`，`360bb7ad4f5af4d6d4d57c2d10b1346081ba41cd`（已推送并核对远端） |
| DevicePack | `ns5039-v1` / schema 1；ESS 保持独立观测模板 |
| build ID | `5145f8a1f726c7c0daf94044928dd90ecb6d6ac180a52fa4da275c5109841c7a` |
| manifest SHA256 | `b7b83b05d5d5623f35b93a32dbe2534bdf9002c07b190f41cc56c7912eeb5270` |
| ELF SHA256 | `6853e2705fbe95a99f01f68f22e2277b1df6a5a84a02847ccf6c8a72ee5d51eb` |
| BIN SHA256 | `bdb4424177fc87dd7a1230cb6eefca301df237c32a468eeb4bdf8b82b96703aa` |

构建发生在提交前，manifest 保留 PC `7fcd8d7`、FW `9a5c50c` 和 dirty=true，
342 项输入快照绑定真实源内容；提交后不回填编号假装重新构建。身份核验输入来自
本地 ELF，不是板上实读 ID。B1 产物已保留，生成头/目标输出/日志/工具链不提交。

真实控制仍默认拒绝；T06 的正向命令测试使用明确离线上下文，状态 0/1 映射不是
NS5039 FSM 授权规则。升级/维护有受控拒绝结果，完整独占编排留 T13。T09 软件
约束仅证明写入瞬间检查公开状态并提交单个标量，不保证后续持续停机或物理 PWM。
T10 没有增加线上代次，不能证明同布局迟到字节完全消歧。

真实板上身份、串口、参数回读、PWM/功率效果、ISR/DMA 时序均 `BENCH_PENDING`，
G1 尚未放行。下一批 B3 按依赖推进 T07（UI归口）、T08（安全观察）、T11（记录回放）。

提交执行使用项目上一提交的 Wanchenrui / GitHub noreply 身份作单次 git 参数，
未更改全局身份配置。FW 仅提交四个已审生产文件；生成身份头、构建产物及原 FW
checkout 均未纳入修改。PC 提交承载本文的最终验收、生产代码和独立反例。
