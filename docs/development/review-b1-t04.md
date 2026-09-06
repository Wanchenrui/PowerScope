# B1 T04 独立审查

审查者firmware_t03，非T04实现者。基线PC cdfc83029c0233e4fea30b59f474c99a50612a03及共享未提交最终diff。结论：发现3项已由session_t04修复，最终专项通过，无剩余T04阻断；BENCH_PENDING。T05目录/ELF代次问题由session_t04另行独审。

审查范围：Session epoch/握手/独占/跨协议在途登记；Debug seq永不复用、挂起匹配、PSC1降级、布局ACK提交与读取分块；MSG无事务号的不确定冻结；main握手/ELF失效与inspector读取分块。只读生产，新增独立`tests/test_t04_review.py`，实现修复由原实现者完成。

关闭的问题：

- SET_SAMPLE成功ACK仅检查4字节，零有效周期也能提交布局。已验证非零才提交；独立反例先送0再送100000，前者不能换布局。
- 非v1普通响应被拒绝，但STREAM_DATA及seq0 WAVE_DATA绕过version检查。已在共同帧入口拒绝未知版本；独立CRC正确的version2两类帧不能分发。
- P1 MSG request_read(0x2001,1)把“read”API标志当只读证据，线上实际仍是开关机写命令，可绕过G0。独立实跑修复前1 failed/2 passed exit1，`build/t03-review-t04-msg.log`。修复后Session绑定的MSG仅允许KNOWN_MSG_COMMANDS的已知read方向和准确字数；2001/2002/未知命令及错误长度发送前拒绝，合法2101状态读取保持。writer override不绕过真实Session门禁。

前两项提出后实现者修复早于独立测试首次执行，首次2 passed，不冒称保存了失败运行。最终独立5反例及原105相关专项 **110 passed in 0.87s / exit0**，`build/t03-review-t04-final.log`。覆盖额外全能力广告+writer override下所有公开Debug控制仍拒绝、无残留pending/Session登记；合法MSG读完正常清登记。命令：

```powershell
$env:QT_QPA_PLATFORM='offscreen'
./.venv/Scripts/python.exe -c "from PySide6.QtWidgets import QApplication; app=QApplication([]); import pytest; raise SystemExit(pytest.main(['tests/test_t04_review.py','tests/test_session_epoch.py','tests/test_protocol_limits_ns5039.py','tests/test_session_controller.py','tests/test_session_lifecycle.py','tests/test_session_review.py','tests/test_debug_service.py','tests/test_debug_request_timeout.py','tests/test_msg_service.py','tests/test_wave_v2.py','tests/test_wave_recorder.py','tests/test_inspector_batch.py','-q']))"
```

新增writer选择的嵌套三元已由实现者整理成简单分支；必要writer-only/旧sink兼容保留，不成为Session真实控制授权旁路。没有大面积旧代码风格重构。最终全套由协调者指定唯一执行者运行，本审查没有并行跑全套。

线格式无epoch/MSG事务号，因此应用进程重启或重开串口仍不证明迟到数据已消失；MSG不确定命令冻结不因clear/reconnect重开。设备同build重启不能可靠自动识别，Debug seq耗尽需后续协议/设备复位证据，当前拒绝继续。真实板上握手、升级与控制效果没有验证，ACK不提升Verified/EffectConfirmed。

## 统一全套后的旧夹具迁移独审

首轮统一全套766 passed/8 failed（exit1/no skip）中，本审查获分配两项夹具迁移，生产继续冻结。`test_device_info_v2.py`原完整字典相等断言全部保留，新增显式DeviceIdentity(protocol_version=2)与空Capabilities，故未知协议没有猜出能力；不是删去失败断言。`test_t02_config_safety.py`原所有真实控制入口0发送及拒绝断言不变，只在读取前注入已知legacy只读能力{1,7}/181，未删除Session、未替换控制授权器，随后仍断言读取恰好发送一次。

独立核对两文件diff，无断言弱化或生产改动；实际专项 **25 passed in 0.73s / exit0**，日志`build/t03-review-t04-fixtures.log`：

```powershell
$env:QT_QPA_PLATFORM='offscreen'
./.venv/Scripts/python.exe -c "from PySide6.QtWidgets import QApplication; app=QApplication([]); import pytest; raise SystemExit(pytest.main(['tests/test_device_info_v2.py','tests/test_t02_config_safety.py','-q']))"
```

这两项迁移独审通过，无阻断；其余6旧夹具由T05实现、session_t04独审，最终全套仍交统一执行者。
