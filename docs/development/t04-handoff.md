# T04 B1 实现交接

状态：CODE_REVIEW；未提交/推送。实现者session_t04，基线PC cdfc83029c0233e4fea30b59f474c99a50612a03。独审交firmware_t03。硬件BENCH_PENDING。

## 文件和接口

- session/session_controller.py：epoch_changed(int,str)、identity_changed(object)、epoch/identity/capabilities/ready，invalidate(reason)，set_artifact_verification(epoch,build_id,manifest_sha256,verified)，negotiate/device_restarted；RAW/upgrade acquire_exclusive/release_exclusive/write_service；Debug/MSG begin_request/end_request阻止跨协议在途竞争。真实serial的公共write要求RAW令牌，Mock兼容演示；最终Transport写仅私有_write_transport。ready不是控制授权。
- core/debug_service.py：绑定Session失效；挂起请求即使无callback也匹配epoch/seq/cmd/成功长度。NACK FF按seq收尾。已使用seq在整个服务生命周期均不复用，含重连，65535耗尽明确拒绝。clear/timeout清布局。SET_SAMPLE扩展u32周期、16项/64字节且匹配有效周期ACK后提交。PSC1完整174 payload才解析扩展；58稳定前缀；未知型号能力未知；旧NS仅保守读。
- core/msg_service.py：单在途，全部请求登记；副作用及读取超时/取消均冻结该command，重连/clear不恢复；其他命令可读状态但不恢复旧配对。无虚假fresh/Verified。真实控制保持G0拒绝。
- ui/main_window.py：最小握手/ELF invalidation/采样超限拒绝，已顺序释放T05接目录；请审查共享最终版本。
- ui/variable_inspector_view.py：大对象/批量调用read_memory_block/read_batch_blocks，按协商上限串行分块且epoch绑定；旧测试FakeDebug兼容回退。
- tests/test_session_epoch.py、test_protocol_limits_ns5039.py新反例；tests/test_debug_service.py迁移真实FW格式夹具。

contracts.py、SerialTransport及ProtocolEngine均未改。

## 验证记录

环境：Windows Python3.12 .venv/Scripts/python.exe，QT_QPA_PLATFORM=offscreen。单独直接pytest会先建QCoreApplication，公共conftest清理期要求topLevelWidgets而报错，因此专项显式QApplication bootstrap（未改公共conftest）。

最终实际执行：`.venv/Scripts/python.exe -c "from PySide6.QtWidgets import QApplication; app=QApplication([]); import pytest; raise SystemExit(pytest.main(['tests/test_session_epoch.py','tests/test_protocol_limits_ns5039.py','tests/test_session_controller.py','tests/test_session_lifecycle.py','tests/test_session_review.py','tests/test_debug_service.py','tests/test_debug_request_timeout.py','tests/test_msg_service.py','tests/test_wave_v2.py','tests/test_wave_recorder.py','tests/test_inspector_batch.py','-q']))"`：105 passed in 0.85s，exit0。git diff --check exit0。

早期69专项65过4失败为旧NS假设：批量32/256改16/128；采样周期u16夹具改u32；空SetSample ACK改有效周期u32；空GetInfo夹具改58稳定前缀，均保留原测试行为目标，后69全过。真实C测试向量由T03提供ns5039-get-info.json，PC新测试真实feed→匹配→解析，固定host build ID不冒称ARM设备身份。

额外Wave/inspector/symbol专项39过1失败：T05正在修改ELF缓存后phantom.elf旧测试FileNotFoundError，已反馈T05修，非T04生产范围。未运行全套（统一独审执行者负责），未执行真实串口/升级/硬件。

## 保留边界

没有线epoch，因此不宣称重开串口/应用重启能证明旧字节消失；seq耗尽需要未来有证据的线重置或协议升级，本轮拒绝继续。MSG类请求一旦不确定永久禁该类，状态读不重开配对。设备重启可通过公开device_restarted失效，并通过GetInfo身份改变检查；同build无线上启动计数不能可靠自动识别任意重启。

RAW与升级仅最小独占服务接口；真实升级UI仍G0默认拒绝，完整编排留T13。能力/identity不是授权器，真实控制保持拒绝。无新增协议事务号，不能用这些离线测试宣称控制Verified/EffectConfirmed。

T04实现文件现释放供独审，修复仍由本实现者执行；main_window最终消费方T05共享顺序交接。独立审查结论待firmware_t03填写，非自审。

独审修复更新：firmware_t03指出并独立验证三项问题，本实现者修复：统一拒绝非v1入站帧（含STREAM/seq0 Wave）；SET_SAMPLE ACK有效周期必须非零；Session绑定MSG按真实KNOWN_MSG_COMMANDS读取方向及精确响应字数白名单，禁止request_read伪装2001/2002/unknown绕过G0。writer选择改简单分支，无嵌套条件表达式。F报告最终独审5新测试+原105专项=110 passed/exit0，日志build/t03-review-t04-final.log；正式独审归review-b1-t04.md，不由实现者自盖章。

统一首轮两项T04夹具迁移：完整device_info_v2字典断言新增DeviceIdentity(protocol2)/Capabilities()默认未知预期，其原诊断字段全部保留；t02_config_safety保持所有真实控制零发送，合法读取前仅补已知只读能力。生产未改。实现者25专项passed/exit0，F独审后25passed/exit0，正式记录review-b1-t04.md；首轮766pass/8fail完整日志b1-first-pytest.log保留。

最终集成结论（2026-09-06）：本轮T04实现已由firmware_t03独立审查并关闭全部阻断，状态更新为CODE_VERIFIED；上述CODE_REVIEW等保留为历史。统一软件验收774 passed in44.89s、exit0、无skip；真实串口/板上身份/升级/功率效果仍BENCH_PENDING，真实控制保持默认拒绝。最终提交组合、构建物hash、提交前dirty manifest说明与T06/T09/T10下批依赖以[B1协调记录](b1-coordination.md)为准，独审见[review-b1-t04.md](review-b1-t04.md)。
