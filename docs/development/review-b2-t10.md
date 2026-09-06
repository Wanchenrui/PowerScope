# B2 T10 独立审查

审查者 firmware_t09（T09 实现者，不是 T10/T06 数据接缝实现者）。
状态：进行中，生产只读；独占 tests/test_t10_review.py 和本文。生产修复分别回交
数据实现者 data_t10 与 Debug 接缝实现者 command_t06，未代写生产代码。

读取 planning T10、最终 T10 handoff、SampleBlock/queue/pipeline/EventBus、真实
Debug/Session 入站调用链及 FW 编码器。固定原始 bytes 使用独立逐位 CRC oracle，
不导入生产帧构造器或生产编码器生成期望输入。测试仅把硬件串口替换为 QObject 信号，
Session sender/连接门禁、双解析器、Debug 定界/CRC/ACK/解码和队列均走真实逻辑。

## 已确认并回交的问题

1. Stream 65535→1 漏掉 seq0 被误判连续回绕；Recorder 有同类问题。
   FW 的 s_list[listId].sequence 和 s_wave.blockSequence 都是 uint16++，包含 0；
   仅 Live s_waveLiveBlockSequence 明确跳 0。已要求按真实路径区分。
2. Live 多通道不是每通道帧递增全局 seq。Dm_PrepareLiveBlock 为一组样本递增一次，
   Dm_BuildLiveFrame 对所有通道回显同一个 seq。真实 (1,ch0),(1,ch1),(2,ch0),(2,ch1)
   在原实现被判第二通道 duplicate INVALID，旧兼容层也拒绝第二通道。
   pipeline 与 Debug 接缝分别回交所有者修复，原实现测试的错误帧序假设也须更正。
3. consumer_drop 不得把 INVALID/UNKNOWN/STALE 放宽成 GAP。队列质量优先级保留，
   消费者缺口附加 flag 与计数。三种状态均有独立测试。
4. 已排队早块之后发生超预算大块拒绝，不能把未来缺口贴回早块。必须留给后继块；
   反例 seq10排队→seq11大块拒绝→drain10→push12 检查时间位置。
5. Stream 的 sequence_gap 对应未知设备缺样总数，不能与已知 consumer 丢1相加后
   冒称总 missing_samples=1。由协调者批准 SampleBlock 追加
   consumer_dropped_samples 默认0，独立保留已知消费者损失数。
   同类反例覆盖原 unknown gap 块被淘汰后，其不确定性不能在后继 clean 块中丢失。

## 首轮证据

- build/t10-review-first.log：3 failed / 6 passed / exit1。两项生产失败是 stream
  wrap 和 INVALID 放宽；第三项是独审 Session 夹具直接私有槽触发 sender 门禁，
  没有真实信号/connected，已修夹具，不计生产缺陷。
- build/t10-review-second.log：2 failed / 9 passed / exit1。首两项修复已过，
  新失败是缺口时间倒置、未知设备缺样总数变精确值。
- build/t10-review-wire.log：2 failed / exit1。Live 组序号和 Recorder seq0 原始
  线格式反例。此轮期间数据实现者已修队列，日志中的生产字段可能含追加默认字段。
- build/t10-review-quality.log：2 failed / 1 passed / exit1。UNKNOWN/STALE 剩余
  同类分支，INVALID 已修复。
- build/t10-review-gap-carry.log：1 failed / exit1。未知设备 gap 被淘汰后消失。

最终结论等待所有剩余失败关闭、最终源码复核与专项复跑。软件证明不替代真实串口、
物理时基/功率控制或台架吞吐；BENCH_PENDING，真实控制默认拒绝。


## 最终独立结论（2026-09-06）

**T10 软件代码及数据接缝独立审查通过，未关闭阻断为零；BENCH_PENDING。**
前述“进行中”及失败是历史定位记录，以下为最后生产冻结后的结论。

独立执行：

```powershell
$env:QT_QPA_PLATFORM='offscreen'
.venv/Scripts/python.exe -c "from PySide6.QtWidgets import QApplication; app=QApplication([]); import pytest; raise SystemExit(pytest.main(['tests/test_t10_review.py','tests/test_t10_samples.py','tests/test_wave_v2.py','tests/test_wave_recorder.py','tests/test_debug_service.py','tests/test_session_epoch.py','tests/test_event_bus.py','-q','--tb=short','-p','no:cacheprovider']))"
```

**87 passed in 0.30s，exit0，无 skip**。日志 `build/t10-review-final.log`，退出码
`build/t10-review-final.exit`；包含 17 个独立用例，与实现者测试范围重叠，不相加。
没有运行 PC 全套。最后单个未知缺样反例历史见 build/t10-review-current.log
（1 failed / 16 passed），现已关闭。

最终修复已逐项只读复核：pipeline 按 list 或 Live channel 维护连续性；Live 组序号
共享且跳0，Recorder/stream 包含0。Debug 兼容层按channel跟踪同组seq；独立固定
RAW codec帧确保四通道帧均有效并分发，不仅测试自建 SampleBlock。
Queue 区分队首淘汰与未来超预算拒绝，按同源附加损失；原INVALID/UNKNOWN/STALE
质量保持，None 总缺样保持未知，已知消费者损失由 consumer_dropped_samples 表达。
被淘汰块携带的损失与未知总数继续传播；各列表/capture/generation 失效时清理相应账目。
当前私有loss tuple保存消费者数、已知设备缺样、未知标志，范围局限于原队列政策，
没有重写codec或引入新线上协议，复杂度与实际反例相称。

额外独立正向证据包括真实Session信号→Debug保留大于2^53的uint64与负double原始
字节、只读typed view、未知tick单位None/ACK实际周期、按list序号、明确NACK恢复
旧ACK布局、stop/clear旧块拒绝、设备累计overflow只计增量、跨列表消费者缺口隔离，
以及同一次Qt detached flush中首handler失效后阻断剩余handler/旧块。
EventBus保留低频控制队列、高频兼容副本受独立预算；批次峰值与总RSS的区别有交接说明。

缺线代次/同capture-list同布局迟到字节的身份仍不能仅由ACK和主机generation证明，
该边界已在T10交接中保留，审查不将其算作硬件重启自动消歧。未知device tick单位
不因值字节有效而变成已知物理时基。固定离线基准的原始结果/输入由T10交接保存；
审查没有把离线吞吐、局部RSS采样或有界队列测试解释成真实串口/功率台架验证。

生产由原实现者修复后冻结；审查者仅提交独审测试和本文供协调者集成，未提交或推送。
