# B2 T06 独立审查

审查者 data_t10，非 T06 实现者。审查最终 `command_service.py`、`parameter_codec.py`、Debug/MSG/Session 控制接缝与实际调用链；T10 数据接缝最终审查由 firmware_t09 负责。本审查未改 T06 生产文件，修复归 command_t06。结论：发现的整数缩放精度阻断已关闭，当前 T06 无未关闭阻断；真实控制默认拒绝，BENCH_PENDING。

独立新增 `tests/test_t06_review.py` 22 项，用手工小端布局和独立逐位 Modbus CRC 拼装完整请求/响应，未调用产品 DebugProtocol 构造期望帧。验证 uint64 锚点读、写、ACK、回读完整字节；0x0C/0x0D 成功 ACK 必须1字节回显、0x0E 必须空响应；错误长度不能推进。精确匹配只提升参数 Verified，状态命令只到 Acked，Effect 保持 Unknown。

其余反例覆盖 descriptor 换址、身份核验撤回、epoch/权限变化、状态源异常（锚点前及ACK后）、截止时间后迟到ACK、短写无Sent且Unknown永久冻结/无重试、只读/来源未知/宽度/对齐/scale/range拒绝和普通构造真实控制全部拒绝。核对实现者相关专项中的整份描述符变更、运行状态/新鲜度、NaN/Inf、未知协议结果和session失效路径，未弱化既有断言。离线0/1运行状态含义仅为明确测试语义，不作为真实NS5039 FSM授权证据。

## 关闭的问题

`encode_parameter` 对整数目标但 scale != 1 使用 `/` 进入 float，例 uint64、scale=2、请求 `(2**63+1)*2`、允许范围 `(0,2**65)`，实际编码得到 `2**63`，丢失最低位但校验仍放行。独立固定字节反例首次 **1 failed / 13 passed / exit1**，`build/t06-review-first.log` 与 `.exit` 保留。实现者改为整数目标用 Fraction 精确执行 scale/offset/工程量回转换；非整数结果明确拒绝，未用容差把分数当整数。独立复核编码字节为 `01 00 00 00 00 00 00 80`，类型宽度/范围检查保留。

## 最终验证

`build/t06-review-final.log` / `.exit`：**132 passed in 0.42s，exit0**，含独立22项及实现者110项相关专项；无skip，未跑全套。命令：

```powershell
$env:QT_QPA_PLATFORM='offscreen'
.venv/Scripts/python.exe -c "from PySide6.QtWidgets import QApplication; app=QApplication([]); import pytest; raise SystemExit(pytest.main(['tests/test_t06_review.py','tests/test_command_service.py','tests/test_debug_service.py','tests/test_debug_request_timeout.py','tests/test_session_epoch.py','tests/test_session_controller.py','tests/test_msg_service.py','tests/test_t04_review.py','tests/test_wave_v2.py','tests/test_wave_recorder.py','-q','--tb=short']))"
```

`git diff --check` exit0。未执行真实串口、真实身份/ELF回读、台架控制/参数效果或升级。G1不因软件独审通过而放行；UI归口T07、安全监督T08、独占升级编排T13仍未计入本批完成。
