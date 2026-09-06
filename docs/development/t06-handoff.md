# T06 B2 命令服务交接

最终状态：CODE_VERIFIED / BENCH_PENDING。data_t10 独审通过，统一全套 888 passed / exit0、无 skip；提交组合见 [B2协调](b2-coordination.md)，独审见 [review-b2-t06.md](review-b2-t06.md)。基线 PC 7fcd8d7；真实控制保持 G0 拒绝。以下未提交/待审等为实现交接时记录。

文件：新增 core/command_service.py、parameter_codec.py、tests/test_command_service.py；修改 core/debug_service.py、msg_service.py、session/session_controller.py。未修改 UI、contracts、公共 conftest。guardrails 无需改动，原配置范围校验不作为控制授权。Wave 两个旧测试曾获预约但没有改动，现释放。

接口：CommandService(session, debug, parameters, state_provider, clock_ns=..., max_age_ns=..., state_alias='running_state')，submit(CommandIntent) 返回 CommandRecord，records 保留逐意图历史；expire() 检查截止时间且有 Qt timer。CommandRecord 保留 intent（请求值）、encoded_value、actual_raw_value、anchor_value/anchor_received_ns、readback_value 与严格阶段 receipts。返回同 intent ID 原记录，无自动重试。多项逐次 submit，只保存逐项结果，不原子提交、不自动回滚。任何有副作用的 Unknown 冻结该服务全部后续控制，换 alias/重连不能重新授权。

明确离线入口 for_offline_test(debug, parameters, OfflineCommandContext, state_provider)：要求 Debug 无绑定 Session，逐阶段再次检查。它不改变真实 Debug/Session G0 门禁；要求 writer 返回完整字节计数，None/短写不产生 Sent。正常构造即使身份/参数/状态都满足仍拒绝真实控制。离线 Observation.raw_value=0/1 显式解释为 stopped/running，默认 alias 为 offline_running_state；这是测试语义，**不是 NS5039 实际 FSM 枚举**，不得在 T07/T08 沿用为真实设备状态解码。真实状态语义、监督和授权仍待后续。

每次锚点返回、真正发送前、ACK、回读重新验证会话 epoch/身份/连接/ready、整份 frozen 参数描述符、权限、有限数值/范围/类型来源/宽度/对齐、运行状态新鲜度/alias、截止时间及独占。异常产出带原因 Rejected（发送后 Unknown），不冒泡成无记录失败。整数目标的缩放/偏移使用精确 Fraction 算术，不经 float 中间值；缩放非整数拒绝；浮点按实际编码后的原始标量精确回读。enum/pointer 等缺完整编码契约的类型拒绝。读锚点为当前 Debug seq 匹配响应，非缓存观测。参数 Verified 不升级 effect。

受控 start/stop/run_mode/clear_fault 已走 Debug；核对真实 FW user/source/debug_monitor_core.c，0x0C/0x0D 成功 ACK 是 1 字节请求回显，0x0E 空 ACK；run_mode 只允许 0/1。状态命令最多 Acked，不声称已停机或效果确认。upgrade/maintenance 有明确受控拒绝结果，设备核验的独占编排留 T13，无 RAW 授权旁路。Debug 增 set_run_mode/clear_fault、纠正 ACK 长度；MSG 增整数短写检查且保留不确定冻结。

T10 预约接缝也由本实现者写入 Debug：SamplePipeline 构造、stream register 和 wave ACK configure（含 points/epoch/build/tick），合法 stream/raw recorder/Live 输入；Live 先解码交 pipeline 再做旧事件兼容，block_seq 为采样组共享序号，兼容检测按 channel 维护（见独审修复补记）；status 输入溢出/部分采集。clear/timeout/重配开始/stop/abort 失效并清旧兼容事件，ACK 提交再清旧队列。pipeline 返回 None 时禁止旧兼容数据分发。匹配当前 SET_SAMPLE 明确 NACK 1..7 恢复旧已ACK布局，timeout/cancel 不恢复。T10 生产与接缝最终独审归指定其他实现者。样本停止后须重新配置确认才重新采纳数据，不能用旧字节恢复。

实际执行（Windows PowerShell，Python .venv）：

```powershell
$env:QT_QPA_PLATFORM='offscreen'
.venv/Scripts/python.exe -c "from PySide6.QtWidgets import QApplication; app=QApplication([]); import pytest; raise SystemExit(pytest.main(['tests/test_command_service.py','tests/test_debug_service.py','tests/test_debug_request_timeout.py','tests/test_session_epoch.py','tests/test_session_controller.py','tests/test_msg_service.py','tests/test_t04_review.py','tests/test_wave_v2.py','tests/test_wave_recorder.py','-q','--tb=short']))" *> build/t06-final.log
$runExit=$LASTEXITCODE
Get-Content build/t06-final.log -Tail 20
Write-Output "EXIT=$runExit"
exit $runExit
```

结果：110 passed in 0.44s / exit0。首轮73专项通过 build/t06-first.log；接缝收紧时 104 passed / 1 failed / exit1，build/t06-pipeline.log，失败为明确 NACK 后旧布局原业务断言；按上述已确认拒绝语义恢复，保留原断言后通过。新增反例覆盖权限/类型/NaN/Inf/uint64/编码缩放/对齐/宽度、状态/身份/目录锚点竞争、ACK回读不一致、短写/无计数、断连/截止时间、重复ID/Unknown冻结、部分完成及状态源抛异常。git diff --check exit0。

未运行全套、ARM 构建、真实串口/板上身份/参数回读/功率或故障清除效果、升级/维护流程：BENCH_PENDING。离线通过不代表 G1 放行。T07 UI归口和 T08 安全监督不属于本批。

业务及 Debug 接缝文件现冻结并释放供独立审查；发现问题仍由原实现者修复，不自最终验收。


独审修复补记：data_t10 用独立字面值测试发现 scale=2 的 uint64 请求 (2**63+1)*2 在旧除法路径静默丢最低位；现整数目标通过 Fraction 精确计算缩放/偏移及回转换范围，只接受分母为1的结果，浮点元数据按其实际表示值解释，不能靠容差舍入成整数。独审原测试不改。firmware_t09 重新核对真实 C 确认 Live 一组多个 channel 共享 block_seq，并非逐帧递增；此前协调建议的 global 检查被撤回，Debug 恢复逐 channel 检查，保留同 channel 重复/倒序拒绝。独立实际 feed (1,ch0),(1,ch1),(2,ch0),(2,ch1) 已恢复全部四块。

实现者组合专项日志 build/t06-review-fixes.log 为102 passed/2 failed/exit1：T06 uint64 和 Live 组独审反例均通过；仅剩 T10 消费者队列 UNKNOWN/STALE 被改为 GAP，已回交 data_t10 原实现者，未跨文件代修。独审最终结果由各独审者补记。修复后再冻结本批生产文件。
