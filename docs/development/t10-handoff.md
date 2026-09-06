# T10 B2 数据块交接

2026-09-06；实现者 data_t10；最终状态 CODE_VERIFIED / BENCH_PENDING，firmware_t09 独审通过。统一全套 888 passed / exit0、无 skip；提交组合见 [B2协调](b2-coordination.md)，独审见 [review-b2-t10.md](review-b2-t10.md)。以下未提交等为实现交接时记录。
未提交/推送。真实控制默认拒绝，串口和台架 BENCH_PENDING。

## 接口和归属

- `core/contracts.py`：SampleBlock 仅追加默认 quality_flags、first_sample_id、layout_generation、consumer_dropped_samples；Quality 和命令冻结语义不变。raw_data 保持 bytes，小端交织行（Live 为单通道行），不转 float。
- `core/sample_pipeline.py`：SamplePipeline configure_stream/configure_wave、invalidate/invalidate_wave、stream/wave/wave_status。保存 dtype、原始数据、epoch/build、list/capture、原始序号、实际 ACK 周期、设备 tick 和 host monotonic_ns。Wave first_sample_id 是序号，不冒充设备 tick；未知 tick 单位保持 None。typed_view 提供只读 NumPy 结构视图，未知 dtype 为 opaque bytes。
- `core/sample_queue.py`：SampleHub 默认 plot 2 MiB、recorder 8 MiB 独立订阅，subscribe(name,budget_bytes) 返回 pull 队列，drain(max_blocks=64)。drop oldest；单块超预算拒绝。预算计原始字节与保守元数据额度；共享不可变数据不会为每个消费者复制原始 payload。队列累计 accepted/drop samples/drop blocks/overflow/invalidated/device-overflow 和字节峰值。consumer_drop 按 epoch/generation/list/capture/channel 分开；设备 overflow_count 由累计状态转增量零样本质量块，不在每个数据块重复累计。
- `core/event_bus.py`：低频控制事件仍 FIFO；高频兼容 var、wave/data、wave/live_block、wave/error，以及 frame/received/debug/response 的 0x10/0x24 副本进入单独 2 MiB 队列并统计丢弃。一次 detached flush 与待排队数据各自最多 2 MiB；其统计峰值表示待排队预算，不是整个进程 RSS。invalidate_data 的 generation 检查阻断低频回调中重配后 detached 旧批次继续派发。
- 实际 WaveCodec 数据适配入口位于 `core/debug_service.py`，由 command_t06 唯一写入接缝；`wave_codec.py` 压缩算法和 Wave v2 线格式未改。stream、Live 解码后、Recorder 原始块均进入 SamplePipeline；ACK 才 configure，停止/重配/失效清队列且禁止旧兼容数据继续分发；匹配明确 NACK 可恢复旧 ACK 布局。
- `tests/test_t10_samples.py`、`scripts/benchmark_t10_samples.py` 为本任务专项。StreamingManager 无需改动，UI/持久化保留 T12/T11；默认 plot/recorder 队列可被后续消费者独立 drain，当前 UI 仍走有界兼容事件。

## 质量与边界

序号回绕、样本计数回绕明确 flags；Live 一组多个通道共享 block_seq，因此逐通道追踪 block_seq 和 sample_id；只有 Live 跳过序号0，stream/Recorder均包含0。重复和倒序为 INVALID，缺序号/缺样为 GAP，旧块不会补值或插值。stream 无样本 ID，缺帧只标 sequence_gap，missing_samples 保持未知。设备回退不能证明一定重启，标 out_of_order_or_restart 并拒绝视作连续有效数据；明确会话失效后重新配置标 restart。Recorder 非零开头、偏移不符和终态不足/已知上传缺口标 partial_capture。

wire 没有 layout generation：队列失效和 ACK 提交不能证明同 capture/list 且同布局的迟到字节属于哪个设备代次；不会宣称完全消歧。Wave 没有真实 device tick，保留未知；设备慢 tick 的单位不代表 1us 测量分辨率。完整记录、磁盘持久化、绘图 UI 与真实线路吞吐均不在本任务验收内。

## 验证

最终专项 `build/t10-final-tests.log` / `.exit`：**87 passed in 0.31s，exit0**。QApplication bootstrap、QT_QPA_PLATFORM=offscreen；包含独立17项审查反例、T10、wave_v2、wave_recorder、debug_service、session_epoch、event_bus。覆盖 uint64 最大值、负 double、Live/Recorder 实际 feed、ACK 提交/停止、独立慢消费者、多列表 gap 隔离、回绕/重复/错序/部分捕获、detach flush 失效，以及真实 Session 接收信号 → Debug 与 ProtocolEngine 双解析的 400 帧压力反例，控制 ACK 副本留低频队列。首次双解析测试直接调用私有槽被 Session sender 门禁拒绝（1 failed/69 passed）；已改为 transport QObject 信号驱动，历史日志 `build/t10-dual-parser-first.log` 保留。

固定离线基准：`.venv/Scripts/python.exe scripts/benchmark_t10_samples.py --output build/t10-benchmark.json`，结果/日志/exit 存 `build/t10-benchmark.*`，exit0。Windows 10 19045、Python 3.12.14，2通道 uint64/double、32行/帧、10000预建帧，每97帧故意缺1帧，共送9897帧，103缺帧全部识别。wall 3.482s、CPU 3.359s（单核96.47%）；RSS起44,912,640、末/采样峰52,453,376字节。plot峰25,680字节无丢块；不读取的 recorder峰8,387,088字节、丢4998块/159936样本；兼容事件峰2,096,659字节、丢323771条。RSS是定期采样而非OS保证的全程最大值。该输入预建、无串口等待、无GUI绘制，不能用3.5秒声称真实串口或台架吞吐。T12/T18可复用该固定输入和配置。

独审修复更新：firmware_t09实际反例推动修复stream/Recorder跳0假设、consumer_drop不能降低INVALID/UNKNOWN/STALE、超预算后块的loss不能回贴之前队头、未知设备缺样保持missing_samples=None。consumer_dropped_samples独立记录已确证主机丢样。真实C证据纠正此前根协调与实现的Live“全局逐帧序号”判断：同组各通道共享同seq，pipeline按每通道追踪，Debug兼容接缝由T06已修。最终独审状态由review-b2-t10.md给出。

最终缺样语义收口：missing_samples=None本身表示未知，无需任何flag，队列丢弃不会把它换成精确数；已确证的主机丢样数仅consumer_dropped_samples。被淘汰块的设备未知/已知缺样也随loss传递；队列淘汰质量不提升INVALID/UNKNOWN/STALE。87项专项通过后生产和测试冻结，F最终独立验收、C统一全套；本实现者不重复全套。

最终None语义冻结后的同一固定基准已重跑，exit0；build/t10-benchmark.json为末版源码结果。wall 3.467s、CPU 3.344s（单核96.45%）、RSS起/末/采样峰 45174784/52690944/52690944字节。队列峰值、丢弃与103缺帧计数保持前述值。上段耗时/RSS保留为此前轮次，末版以本段和JSON为准。
