# NS5039 首轮参数目录（T05输入，非运行授权）

基线同protocol-contract-v1.md。别名及显示范围来源 `power_scope/profiles/ns800rt_smoke.yaml:28..49`；固件权限来源实际 `debug_monitor_core.c:s_writeRules`。本轮18项已由独立审查者直接核对ELF的.symtab根地址与DWARF成员偏移，均为float/4字节，地址证据固化于[SHA绑定fixture](../../tests/fixtures/c01_20260821_addresses.json)，仅适用ELF SHA256 `80b8ba7c699df7316c1e5d084bd37112e36c589bd9c7d90cd94fea47c0d9f9ec`。以下所有18项**离线ELF解析状态=已核验，板上身份/设备可读状态=待匹配build ID及验证，当前生效=未实测，可整定=未验证**。表中写范围不是主机已开放写权限。

| 别名 | 精确符号 | 显示范围 | FW写范围（原始值） | 静态控制证据 |
|---|---|---|---|---|
| inv_curr_freq_kp | g_invCurrLoopCfg.freqCfg.kp | -10000..0 | 无 | PI调用注释 |
| inv_curr_freq_ki | g_invCurrLoopCfg.freqCfg.kiTc | -1..1 | 无 | PI调用注释 |
| inv_curr_pri_kp | g_invCurrLoopCfg.priDutyCfg.kp | 0..0.1 | -10..10 | PI调用注释 |
| inv_curr_pri_ki | g_invCurrLoopCfg.priDutyCfg.kiTc | 0..0.1 | -1..1 | PI调用注释 |
| inv_curr_phase_kp | g_invCurrLoopCfg.phsCfg.kp | 0..0.2 | -10..10 | PI调用注释 |
| inv_curr_phase_ki | g_invCurrLoopCfg.phsCfg.kiTc | -0.1..0.1 | -1..1 | PI调用注释 |
| inv_volt_kp | g_invVoltLoopCfg.voltCfg.kp | 0..0.1 | -100..100 | 启用后PI调用 |
| inv_volt_ki | g_invVoltLoopCfg.voltCfg.kiTc | 0..0.1 | -1..1 | 启用后PI调用 |
| current_limit_kp | g_iLmtLoopCfg.iLmtCfg.kp | 0..2 | 无 | 本轮未确认 |
| current_limit_ki | g_iLmtLoopCfg.iLmtCfg.kiTc | 0..2 | 无 | 本轮未确认 |
| urms_kp | g_uRmsLoopCfg.urmsCfg.kp | 0..0.1 | -10..10 | 启用后PI调用 |
| urms_ki | g_uRmsLoopCfg.urmsCfg.kiTc | 0..0.1 | -1..1 | 启用后PI调用 |
| active_power_kp | g_aplCfg.cfg.kp | -1..1 | 无 | slice6有APL_Process；参数作用未核验 |
| active_power_ki | g_aplCfg.cfg.kiTc | -1..1 | 无 | 同上 |
| reactive_power_kp | g_rplCfg.cfg.kp | -1..1 | 无 | slice2条件调用RPL_Process；参数作用未核验 |
| reactive_power_ki | g_rplCfg.cfg.kiTc | -1..1 | 无 | 同上 |
| spll_kp | g_spllCfg.kp | -1000..1000 | 无 | 有SPLL_Process；参数作用未核验 |
| spll_ki | g_spllCfg.kiTc | -1000..1000 | 无 | 同上 |

恰8/18字段在参数ACL；另外 `g_uRmsLoopCfg.urmsRef` 为binary32、80..140（不属于18增益字段），`g_uart_debug_scratch` 是专用4字节测试区，不能当第十个控制参数。FW拒绝NaN/Inf，范围为闭区间，不扩大权限也不修改保护阈值。

类型证据分层：白名单8项按FW验证器明确作为4字节float解释；本轮匹配上述hash的离线ELF另为全部18项提供DWARF float/4字节证据，不能由`.kp`/`.kiTc`后缀猜类型。T05可消费fixture中的本地类型/地址证据，但仍须核验板上build ID；换成其他hash必须重新解析核对，不能沿用此绝对地址。未知类型时descriptor.dtype/byte_size/address保持None、权限False；离线解析成功本身不授予权限。单位/标定未知保持None，scale=1/offset=0只代表保留原始值。显示精度和显示范围不是校准或写权限。

`inv_currloop.c:23..40`初始化使用FPWM_DIV4；`INV_CurrLoopProcess`中三个PI调用全部注释，实际输出来自3/5次SIRC再夹至±0.5。4个可写电流字段不得列为可自动整定。`inv_voltLoop.c:21..34,83..93`启用条件为state不等于STATE_DISABLE，PI输出与SIRC叠加，PI限幅±5；`urms_loop.c:19..28,52..63`为LOOP_DISABLE提前返回，PI前馈urmsFrd、限幅0..180。

`ns800rt/common/common.h:142..146`定义40kHz、FPWM_DIV4/12；`user_interrupt.c`电流在slice2/6/10、电压slice4/8/12、RMS slice9，名义周期分别100/100/300us。模式/使能仍影响实际运行；这些静态周期不能替代采样有效周期或台架测量。初始化`kiTc = Ki / ctrlFreq`支持Ki×Tc解释，但PI_CTRL_ProcessLmt来自预编译控制库，最终离散实现、积分限幅/复位/抗饱和不可凭调用名确定。T15需库hash和可观测输入输出证据后才能做系数转换。

T05下一步生成机器差异报告，逐项独立列resolved/readable/ACL/effect/tunable及证据，不能用一个enabled布尔合并五个状态。首轮写候选仅停机单参数且身份、类型、回读新鲜度均成立；允许模式目前空集合，需设备状态定义证据后填。`pllPhase`解析失败应禁订阅并报告；不可自动替换成相似名字。换ELF/profile立即失效解析与权限缓存。ESS观察模板不得继承此目录。
