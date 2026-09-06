# 开发交接：B1 已验收，保留 G0 历史

2026-09-06 更新：T03、T04 剩余软件部分与 T05 已完成本轮实现及独立审查，统一全套
**774 passed in 44.89s / exit0，无 skip**；真实固件 C 检查、ARM 全量重建及本地
manifest 交叉核验通过。后续基线使用本文所属 PC B1 提交及 FW
`9a5c50cea54ef063f84a5837e3fbb17ca59d2a11`，不要重新从早期 G0 基线开工。

完整文件归属、审查阻断关闭、命令、构建物哈希与限制见 [B1 协调记录](b1-coordination.md)。
任务交接见 [T03](t03-handoff.md)、[T04](t04-handoff.md)、[T05](t05-handoff.md)。
下一批按依赖推进 T06/T09/T10；真实控制仍默认拒绝，真实串口、板上身份和功率效果
仍 `BENCH_PENDING`，G1 尚未放行。没有线上启动代次的同 build 重启识别、旧 MSG 歧义
恢复及 Debug 序号耗尽边界保留在 T04 记录中。

以下是 G0 交接时的历史任务包，“未完成/proposed”等状态已由上述 B1 记录更新。

## G0 后续可执行任务包（历史）

基线：PC e2ce8ab，分支plan/g0-reliability-foundation；FW 3469da8eaeb2b5657381df49817e350f35964c15，只读。实际dirty清单、ELF/bin/库hash、构建器及基线测试以T00交接为准。T01新增contracts.py、protocol-contract-v1.md、ns5039-parameter-catalog.md、test_contracts.py和本文；不改业务/UI/配置/FW，不提交git。schema1尚未接入业务，不能宣称写闭环已完成。

| 下一任务 | 输入和允许范围 | 必须交付的独立反例/退出条件 |
|---|---|---|
| T03实际FW | 协议文档冻结扩展；实际debug_monitor_core.c/h、build ID与链接保留段；uart_msg_port按需预约 | 实际C处理路径181成功、182/192/193明确LENGTH，截断、坏CRC、跨区间/溢出、16/17、64/超64；能力与ID真实导出、目标构建/map；不改ACL/算法/预编译库；无台架则BENCH_PENDING |
| T04后续请求闭环 | T04-A传输生命周期已完成；后续Session/DebugService/MsgService按独立文件预约迁移 | 完整请求epoch与挂起请求失效；同一transport内迟到响应不能推进新请求；MSG A超时迟到ACK不能完成B，无法消歧就禁用；补齐能力/身份协商与缓存、布局代次；不能用T04-A的sender身份宣称解决全部ACK歧义 |
| T05目录 | 契约与18项静态清单、T02释放后配置文件、ELF适配和最小manifest生成 | 每字段五状态及证据，8/18 ACL准确、10项拒绝写、电流注释PI不可整定，未知类型/身份默认拒绝，换ELF失效缓存；pllPhase报告不猜替代；ESS隔离；不改FW |

T02临时边界：统一control_check回调默认拒绝真实侧控制，只读/Mock保留；跨设备族hotreload明确拒绝并提示重新打开。此为临时收口，不是完整CommandService，后续T06/T07需逐入口迁移和独立审查。

T04-A已完成并独立审查：Session错误更新真实state，短写/异常不报data_sent且拒绝后续写；重连清协议解析缓冲，旧transport/reader排队信号按sender拒绝；读线程stop-before-run及关闭唤醒，超时保留资源并禁止重开；串口write_timeout=1秒；窗口error态也释放传输，关闭失败保留窗口和资源。config_safety实现、contracts独审，18项专项通过。此轮未消除同一transport内请求迟到ACK或完整epoch/身份能力缺口，见T04后续任务。

消费接口：从`power_scope.core.contracts`导入四组frozen dataclass；无新增依赖。未知值None、权限默认False/空集合；Receipt.phase与effect分离。只读块上限helper拒绝182..193，64字节限制仅采样行而非ReadBatch。GetInfo proposed扩展从94开始、80字节，需C/F独立审查后T03实现。

验证命令（Windows PowerShell）：`$env:QT_QPA_PLATFORM='offscreen'; .venv/Scripts/python.exe -m pytest tests/test_contracts.py -q`。2026-09-06实际执行，Python3.12.14，退出码0，5 passed in 0.03s；`git diff --check`退出码0。固定native向量仅PC编码证据，真实FW执行和硬件效果未测。独立审查完成前状态CODE_REVIEW；参数目录为T05输入初稿。构建身份方案未实施、现存ELF未与板上ID核验，真实地址写能力保持受限。

审查更新（2026-09-06）：T01由contracts实现、config_safety独立对照真实FW审查，5项契约测试退出0，无阻断，状态为**代码契约已审查**。上文CODE_REVIEW为首次交接时状态；T03/GetInfo扩展/build ID等proposed仍未实现，硬件仍BENCH_PENDING。最终集成放行由协调者决定。

文件归属：T01新增五文件已完成本轮独立审查并释放；T03/T04/T05不得各自另建同名结构，改接口先通知协调者与消费方。下一任务交接必须列文件、实际命令/退出码、接口变化、未运行项及原因、独立审查结论、台架待验和文件释放。

最终验收（2026-09-06）：协调者实跑**724 Python测试通过，25.45s，exit0，无skip**，日志`build/final-pytest-verified.log`；offscreen并显式提供SHA80b8...现存ELF。T00 **34/34 native C测试通过**；`git diff --check`退出0，FW3469da8e工作区clean、ELF hash未改变。当前G0与T04-A代码范围已验收，独立审查详见[review-g0.md](review-g0.md)，文件冻结供发布。

ARM重建、真实串口和台架尚未运行；T03 proposed固件修复/build ID、T04完整能力与请求生命周期、T05目录运行接入、T06命令闭环及后续验证继续按上表执行。真实地址写仍受限，BENCH_PENDING不被本轮离线通过覆盖。
