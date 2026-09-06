# G0 独立审查记录

2026-09-06；PC基线e2ce8ab，共享分支plan/g0-reliability-foundation，未提交的审查快照。T02实现者config_safety、T00实现者environment；独立审查者contracts（T01实现者，**不自审T01**），GPT-6 Astra / medium。范围为默认拒绝、配置隔离、异步副作用门禁及可复现环境。

## T01：实现与独立审查配对

T01实现者contracts，独立审查者config_safety（GPT-6 Astra / medium）；协调者转交审查结果：已对照实际FW复核181边界、GetInfo现有94字节及proposed174字节payload/185字节响应、8项增益ACL中4项PI调用未启用，以及Receipt阶段/生效证据分离。契约专项5项通过、退出0，无阻断。状态为代码契约已审查；GetInfo扩展、build ID和T03协议修复仍是proposed，未修改FW，未以该审查替代台架。

## T02：本轮范围内未发现未关闭阻断

独立生产代码阅读覆盖device_profile、guardrails、AI确认、MainWindow/profile生命周期、C01 adapter隔离、四个独立写视图和SafetyController。本轮真实控制默认拒绝，Mock明确模拟，读取保持。跨族profile切换在修改前拒绝；同族切换断连、清symbols/AI缓存/Debug布局并替换Safety。缺少或异常control_check返回拒绝；异步写、回退和停机前重检。发现的AI“模拟写后等待设备确认”措辞已交实现者修正并复核。

`tests/test_g0_review.py`四个独立检查：

1. 范围[-10,-1]请求-0.99必须拒绝且不改请求；原e2ce8ab实测allowed=True、值变-1。
2. AI确认不能沿用历史clamped值绕过当前原值校验；原e2ce8ab在校验器缺失时仍调用writer一次，当前零写并明确拒绝。
3. 首项写等待callback时撤销Mock权限，迟到失败callback原本将触发回退；当前无新增write/stop、CONTROL_BLOCKED，提示设备状态未确认，不提示已回退/已停机。
4. Safety无control_check时begin拒绝，读写调用均为零。

原源码通过`git show e2ce8ab:path`只读动态加载验证反例，不修改工作树；首次加载因BOM失败退出1，使用utf-8-sig后退出0并确认上述旧行为。当前专项最终命令：`QT_QPA_PLATFORM=offscreen`下 `.venv/Scripts/python.exe -m pytest tests/test_g0_review.py tests/test_t02_config_safety.py tests/test_native_abi.py -q`，退出0，**27 passed in 0.69s**。包含实现者profile缓存、真实入口拒绝/读取保留及AI拒绝展示回归；不重复全套，最终集成全套由协调者统一计数。

## T00：脚本与ABI审查

已读setup-environment.ps1、build-native.ps1、依赖锁、native_abi_probe.c/test_native_abi.py及environment.md。环境脚本限定Python3.12、建立项目venv、固定依赖并pip check；编译脚本失败即止，默认输出build/native，仅显式-Install覆盖根DLL，源码不被修改。ABI测试从生产C头文件独立求结构大小/偏移，与ctypes实物对比并验标准CRC；上面专项运行已通过。未为审查重复安装依赖或覆盖DLL，实际C构建34/34的证据归T00执行日志，不冒称审查者重跑。

四项外部ELF测试显式输入/缺失skip行为与个人路径移除已检查。审查者直接用elftools遍历.symtab及DWARF成员常量偏移（不调用被测ELFParser/resolve_symbol_path），核实SHA256 `80b8ba7c699df7316c1e5d084bd37112e36c589bd9c7d90cd94fea47c0d9f9ec`的18增益叶子均float/4字节。频率Kp是根200045F8+4=200045FC，历史2000208C不适用。已逐项复核environment落地的`tests/fixtures/c01_20260821_addresses.json`，SHA、18地址及根/成员偏移全部一致；未知hash仅跳过无oracle的固定地址断言，其他解析/类型检查仍执行。T00实现者最终环境专项8 passed/exit0；环境文档旧oracle段和库hash空格已修并复核。T00文件已释放，本轮环境审查无未关闭阻断。

## T04-A：传输生命周期独立审查

实现者config_safety，独立审查者contracts，均GPT-6 Astra / medium。审查SessionController、SerialTransport、必要MainWindow.closeEvent及生命周期测试；没有扩大到能力协商或完整请求epoch。

独立`tests/test_session_review.py`先建立两项真实失败：后台Python线程向旧transport发数据/错误，主线程替换transport后才pump Qt，旧数据仍进入新会话；短写len-1仍报告data_sent。这两项在实现前2 failed/exit1，实现后通过。另外独立验证串口close抛错时保留handle/reader引用且不报关闭成功，重试成功才释放；Serial构造必须设置有限正write_timeout。

主协调审查发现的两个阻断已关闭并复核：write_timeout明确1秒；窗口error态也调用disconnect，close失败忽略关闭事件并保留窗口/资源，成功后才cleanup及调用父类closeEvent。实现者真实MainWindow回归覆盖error态成功关闭及超时拒绝关窗，已由审查者运行。stop-before-run、cancel_read失败后close唤醒真实QThread、超时保留引用/禁止重开、旧reader排队事件、底层handle意外关闭转error、open启动异常清理一并检查。

最终一次专项 `.venv/Scripts/python.exe -m pytest tests/test_session_review.py tests/test_session_lifecycle.py -q`（offscreen），**18 passed in 0.46s / exit0**。本轮T04-A范围内无未关闭阻断；生产文件审查只读，新增独立review测试。短写/异常不再发完整data_sent；旧transport/reader事件按sender身份丢弃；Session错误真实改变state并拒绝后续写。线程退出超时不宣称资源已释放。

## 最终集成测试收尾审查

协调者首轮全套720 passed/4 failed后，两项窄范围测试修复由contracts独审：config_safety为`test_debug_request_timeout.py`两处Safety的内存writer及`test_symbol_search.py`一处FakeDebug编码sink补显式control_check许可，共三处测试夹具迁移，原超时、恢复状态及编码字节断言未修改；生产默认拒绝由独立反例继续覆盖。

environment仅在`test_llm_engine.py`增加autouse tmp_path隔离NeuralTuner模型缓存。该测试原先读取用户训练状态导致Kp结果不同；现在仍执行真实固定seed训练，不Mock预测，不改Kp<0.85断言，不改生产算法。审查已核对缓存路径修改范围；此前正则将目标5%混作实测等已有算法问题留后续，不用此测试证明模型可安全整定。

独审专项 `.venv/Scripts/python.exe -m pytest tests/test_debug_request_timeout.py tests/test_symbol_search.py tests/test_llm_engine.py -q`（offscreen）：**46 passed in 3.72s / exit0**。本次小收尾无阻断；未重复全套，第二次统一验收仍由协调者执行。

## 保留限制

T02不是CommandService，门禁回调不是固件身份验证；它仅暂时禁止真实副作用。T04-A已处理传输错误state、短写、旧transport/reader事件及关闭生命周期；完整请求epoch、同一transport内迟到Debug响应/旧MSG无序号ACK、缓存与观察代次仍留T04后续。完整观察新鲜度及真正停机/回退确认留T08。现有Safety的“原子”及停止成功措辞不构成硬件证据，真实路径继续禁用；不能以Mock测试宣称真实停机安全。FW只读，未重建/未做真实串口与台架，BENCH_PENDING。

本轮审查生产文件只读，仅新增独立测试和本文。不复用本轮结论覆盖后续新改动。

## 最终验收盖章（2026-09-06）

协调者已实际运行最终统一全套：**724 Python tests passed in 25.45s，exit0，无skip**，日志`build/final-pytest-verified.log`；环境为offscreen，显式提供SHA256 `80b8ba7c699df7316c1e5d084bd37112e36c589bd9c7d90cd94fea47c0d9f9ec`的现存ELF。结合T00实际执行的**34/34 native C测试通过**，当前G0与T04-A代码范围已验收。此前720/4失败已由上述测试收尾修复关闭，保留历史以便追溯。协调者另确认`git diff --check`退出0、FW提交3469da8e工作区clean且ELF hash未改变。本次记录基于协调者交付的执行结果，审查者未重复全套。

ARM目标重建、真实串口、升级与带电台架未做，仍BENCH_PENDING。T03实际FW边界/身份实现、T04完整能力协商与请求epoch/迟到ACK闭环、T05运行目录接入、T06统一CommandService及后续硬件效果验证仍未完成；不把G0代码验收表述为这些能力已发布。版本发布由协调者放行，文件已冻结交付。
