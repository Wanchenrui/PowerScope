# B2 T09 独立审查

审查者 command_t06，非 T09 实现者；审查生产只读。结论：T09 本批范围无未关闭软件阻断，独立专项通过；真实控制继续 G0 拒绝，硬件 BENCH_PENDING。

审查真实 FW 工作树 build/fw-t03（9a5c50c 后冻结 diff），涉及 debug_monitor_core.c/.h、uart_msg_port.c、新私有 debug_parameter_write_impl.h，以及最终 ARM 产物 build/t09-identity-final-v2。没有修改 FW 生产文件或实现者测试。

新增独立 tests/test_t09_review.py、firmware_ns5039/t09_review_driver.c、t09_review_state.h。仅复用实际生产 dispatcher/policy 和 B1 独立 driver 的串口/RAM 接缝，不包含 t09_state_fixture.h/test_core.c/t09_driver.c，不使用实现者运行矩阵或生产编码函数生成测试期望。原 review_driver.c 仅补新真实 policy 所需 HAL/state hooks 与两项地址映射，tests/test_t03_review.py 原断言全部保留。

核对和测试要点：

- 真实 WRITE_MEM=2 与 SET_PARAM=8 经过同一既有 ACL、有限值/范围检查后才进入状态门禁。九项 ACL 地址表达式和上下界由原独立 B1 测试保持不变。
- 独立 raw C 请求覆盖 IDLE 单标量成功；RUN/SHUTDOWN（即使 OFF）、未知 FSM、ON、PWM pending/未知值、未知消费者状态拒绝；fault/未知保护事件拒绝。字面值期望为旧值 0x3e800000 或请求 0x3f000000，不由生产编码生成。
- 独立 __disable_irq 接缝在关中断瞬间注入保护锁存，实际状态复核拒绝写入，证明不是在临界区之前读一次许可即放行。原 mask=0/1 均恢复；snapshot generation 从 FFFFFFFE 正常回绕至 0；拒绝数值未进入写入临界区。scratch 仍独立，故障时可写 scratch 不开放真实参数。
- STOP ACK 仍只表示命令受理，当前 FSM/消费者/PWM 软件状态单独记录。观测 48 字节和 last_write_status 4 字节由实际 ELF 符号确认；不把软件 PWM 字段当实际电气状态。
- 独立重新执行 ARM objdump（build/t09-independent-disassembly.log，exit0）：保存 PRIMASK→cpsid i→真实状态检查→单条 STR→DMB→恢复原 PRIMASK，memcpy 在屏蔽前，未见临界区内大复制/发包。
- 最终 manifest SHA b7b83b05d5d5623f35b93a32dbe2534bdf9002c07b190f41cc56c7912eeb5270；ELF 内嵌 ID 5145f8a1f726c7c0daf94044928dd90ecb6d6ac180a52fa4da275c5109841c7a；PC verify_manifest 用该离线 ID 核验通过，错误 ID 拒绝，全部 342 当前源文件 hash 匹配构建输入。核验涵盖 ELF/BIN/lib/dirty source snapshot；未冒称读取板上 ID。

实际命令：

```powershell
$env:QT_QPA_PLATFORM='offscreen'
$env:POWERSCOPE_TEST_FW='D:/GitHub/PowerScope/build/fw-t03'
$env:POWERSCOPE_TEST_HOST_CC='D:/GitHub/PowerScope/build/toolchain/bin/gcc.exe'
.venv/Scripts/python.exe -m pytest tests/test_t09_review.py tests/test_t03_review.py tests/test_t09_firmware.py -q -s -p no:cacheprovider *> build/t09-independent-final.log
```

结果 **41 passed in 1.46s / exit0，无 skip**。内含实现者真实 C 专项 474 checks，与 Python 计数重叠，不相加。独立测试首轮 **39 passed / 2 failed / exit1**，build/t09-independent-first.log：审查夹具把 -1 误当超限（原 kp ACL 为 [-100,100]），以及 Windows 默认 GBK 读取 UTF8 manifest。修正为真实超限最大有限 float 和显式 UTF8 后通过；这是审查测试修复，不是生产缺陷，未放宽原 ACL/生产校验。专项 diff-check exit0。

未重跑全套或目标构建（只独立核验现存最终构建物）；未连接串口/烧录/带电操作。NMI、40kHz ISR 实际预算、物理 PWM、故障停机时延和真实功率效果仍 BENCH_PENDING。软件约束是写入瞬间消费者禁用和单标量提交，不保证未来持续停机，不引入多参数原子事务。G1 未放行。

审查测试及文档文件现释放。发现的测试夹具问题已关闭，没有需要实现者生产修复的问题。
