# PowerScope consumer contract v1

状态：T01 冻结线格式；B1 T03/T04/T05已实现并独立审查，Python契约已接入会话与目录。线版本仍为 1，schema 版本独立为 1。历史基线依据 PC e2ce8ab、FW 3469da8eaeb2b5657381df49817e350f35964c15 的实际 `user/source/debug_monitor_core.c` 与同名头文件；不以 `mcu_debug_stub` 为证据。

## 实际线格式与边界

所有多字节整数小端；目标内存浮点按 IEEE754 binary32/binary64 小端原样传输。CRC16/Modbus 初值 FFFF、多项式反射 A001、无最终异或，覆盖 SOF 到 payload，CRC 小端。标准校验 `123456789 → 4B37`。

| 帧 | 字节偏移（0起） | 总长度 |
|---|---|---|
| 请求 | 0:A5 5A，2:version u8，3:cmd u8，4:seq u16，6:address u32，10:payload length u16，12:payload，末2:CRC | 14+N |
| 普通响应 | 0:A5 5A，2:version，3:cmd，4:seq u16，6:status u8，7:length u16，9:payload，末2:CRC | 11+N |
| STREAM_DATA 10h | 0:A5 5A，2:version，3:10，4:seq u16，6:first tick u32，10:list u8，11:count u8，12:行数据，末2:CRC | 14+数据 |

请求有效载荷上限192、请求整帧206；响应整帧192、普通响应数据上限181。ReadMemory(01) 的 payload 恰为一个非零 u8 长度。历史基线允许1..192，182..192读取后在组帧处静默丢响应，这是缺陷，不是成功。**T03已实现**：上限从响应容量推导181，182..193在读取前明确NACK LENGTH；实际C路径已验证。T04 PC采用1..181协商分块上限。

ReadBatch(03)：`count u8 + count × (address u32,size u8)`；1..16项，size=1/2/4/8，最多128字节数据，不受采样行64限制。0/17项或载荷长度不等 → LENGTH；非法size/地址 → ADDRESS。读区间必须整体落在 Flash `[08000000,08080000)`、DTCM `[20000000,20010000)` 或 SRAM `[20100000,20140000)`，零长度/32位加法溢出/跨区间不合法。

SetSample(04)：旧头 `list u8,period_us u16,count u8` 或扩展头 `list u8,period_us u32,count u8`，后跟 `address u32,size u8,type u8`；解析器以扩展长度精确匹配选择格式。列表0/1，1..16项，整行≤64字节，size=1/2/4/8；8字节对齐4，其余自然对齐。非法列表/数量/周期/总长度 → LIST_FULL；地址/对齐/行宽错误 → ADDRESS；带宽不足 → BUSY。临时对象验证后提交已有实现必须保留。ACK返回有效周期u32，主机仅在ACK后换布局。25us是ISR基准，常规流周期还受115200波特率65%预算及其他列表影响；不能把25us宣称为所有配置有效最小周期。

SetSample另有快速流门槛：计算后的有效周期<5000us且行宽>16字节时PROTECTED。不能只检查16项/64字节就保证配置获准。

WriteMemory(02)/SetParam(08)：同一ACL；参数必须准确4字节、白名单地址、有限binary32且在固件范围内，否则PROTECTED；scratch允许完全落在专用4字节区内的非零写。ACK只说明memcpy已执行，不代表PI参与计算或功率状态改变。

状态码：00 OK；01 CRC；02 COMMAND；03 ADDRESS；04 LENGTH；05 BUSY；06 PROTECTED；07 LIST_FULL。错误响应cmd=FF并回显seq；不能从NACK的cmd恢复原命令，应查挂起请求。RESET(0A)明确PROTECTED；未知命令COMMAND。帧不足14或SOF错静默丢弃；版本错、载荷>192、整帧长度不等先LENGTH；然后校验CRC。传输拆包必须先组完整帧，不能把分段输入当固件截断帧。

设备控制0C、运行模式0D、清故障0E和Wave20..26现有实现；头文件枚举本身不能用于推导命令已支持。响应暂存槽只有1项，满时可能丢响应；T03新增ELF可观测volatile u32 `g_dm_response_drops`（后台自增，u32回绕），不改变旧GetInfo字段；超时是Unknown。流看门狗为3,000,000us且需流中GetInfo启用，不是功率停机保证。

## GetInfo：旧前缀与已实现扩展

旧FW空请求返回94字节payload，T03返回174字节。T04 `DebugService.parse_device_info` 已要求完整58字节稳定前缀，并逐长度读取可选字段；短扩展不得补零伪造能力。

| 偏移 | 实际字段 |
|---|---|
| 0..31 | NUL填充ASCII型号 NS800RT5039 |
| 32 u32 /36 u32 /40 u16 | CPU 240000000 Hz / elf_crc=0 / 协议1 |
| 42..57 | NUL填充ASCII `20260827-wave-v2` |
| 58/62/66/70 u32 | ring drops / TX busy retries / TX recovery / last init error |
| 74/78 u32 | STIM1/STIM3最大cycles |
| 82 u32 | feature_flags=FF（源码注释 DMA/FIFO/v2/trigger/live/64b/DWT/auto） |
| 86 u32 /90 u16 /92 u8 /93 u8 | wave buffer131072 / block points512 / channels16 / descriptor bytes10 |

**T03已实现的固定扩展**：从94追加：94..97 ASCII `PSC1`；98 u8扩展版本1；99 u8扩展长度80（包含magic）；100..131 build_id 32原始字节；132..163支持命令256位位图（cmd c 对应 byte c//8 的 bit c%8，RESET不置位）；164 u16 RX payload192；166 u16 TX frame192；168 u8 batch16；169 u8 lists2；170 u8 sample items16；171 u8 row bytes64；172 u16 ISR tick_us25。总payload174，响应185≤192。扩展恰满80才接受；未来版本/未知magic保持受限。read_memory_bytes从TX减11并由版本1规则上限181推导；有效周期仍取配置ACK。设备tick25仅指ISR采样时基，不指背景`dbg_get_timestamp_us()`（毫秒tick×1000）。

旧PC/新FW：保持0..93原样，追加字段被旧解析器忽略；旧PC本身写策略缺陷不因此消失。新PC/旧FW：受限观测、固定保守读上限，不授权地址写/试验；新PC/新FW：身份与构建物核验、类型、ACL、状态和新鲜度全部满足后才有资格进入后续CommandService。未知设备不得套用NS白名单。

## 构建身份（T03已实现并完成ARM重建）

生成前置 canonical UTF-8 JSON（排序键、无空白），包含FW commit、dirty布尔、所有构建输入相对路径与SHA256（包括未跟踪构建输入）、工具链版本、编译/链接选项、静态库SHA256、型号；排除生成build_id文件、ELF/bin及最终manifest。对这些字节求SHA256作为32字节build ID，生成const数组置`.powerscope_build_id`，链接脚本KEEP该节，由GetInfo读取。可复现构建不得把时间/本地绝对路径放入标识输入；记录时间可在manifest。dirty=true只记录标志不足，必须保存输入摘要及可重建补丁/源码快照。

构建完成manifest绑定build ID、上述输入记录、PC/FW commits、DevicePack版本、ELF/bin/所有控制静态库SHA256、工具链/ABI/链接选项及内存区间；manifest自身hash由PC本地记录，不能再塞回参与构建的输入形成循环。`artifacts_verified`仅由核验器在设备ID等于manifest ID且本地ELF/bin/hash一致时设置；不依据版本字符串、elf_crc=0或ELF符号存在设置。它不是设备认证。T00现存ELF只作历史构建物；T03已用匹配主编译器的Arm GNU12.3.1在独立工作树全量重建，最终manifest/ELF/bin及源码快照通过T05离线核验。板上ID和硬件效果仍BENCH_PENDING。精确schema、canonical输入/相对路径、脚本和实际命令见[ T03交接 ](../development/t03-handoff.md)。

## Python消费语义

单模块 `power_scope.core.contracts` 仅数据，不代替授权器。None=未知，空命令集合/运行模式集合=未获授权，False=未证明允许；调用方不得bool(None)之外自行猜测类型。dtype使用显式小端名`<f4/<f8/<i4/<u4`等及`|u1`，byte_size必须与可信类型来源一致；地址来自匹配构建ELF，DevicePack类型必须绑定版本。scale/offset仅显示换算，raw字段保留原始整数精度；参数范围指编码前原始值域，显示量程不得进入write_range。所有Permission字段只是必要证据，单个writable=True不授权发送。

Observation.host_received_ns / intent.deadline_ns为同一主机monotonic_ns域；设备tick与host时钟不得直接相减。新鲜度由消费方按alias配置TTL计算，每个关键量独立检查。SampleBlock.raw_data为按channels顺序排列的紧凑小端行，sample_count×各byte_size总和必须等于字节数；未知dtype/size拒绝解码，原始数据可受限保存。缺口/溢出未知用None，不写0；设备时间回绕由适配器展开或标GAP，不编造同步证据。

epoch在新连接、断连/串口错误、设备重启识别、profile/ELF切换、升级开始及升级后重新握手时使旧请求、观察缓存和采样布局失效。具体递增由唯一Session管理；不要求一次生命周期固定加几次，只要求从不复用失效代次。Debug响应须匹配epoch、线seq和预期命令；短写不可标Sent，收到完整字节数才是Sent。ACK不是Verified。参数Verified需本epoch且命令后新鲜原始类型回读；float比较编码后值，整数精确比较。EffectState.CONFIRMED必须另有模式、环使能或实际输出证据。Rejected表示发送前拒绝/确定NACK；发送后断连、超时、歧义均Unknown并保留evidence。

旧MSG ACK只有命令号，没有seq/epoch。串行化防同时竞争但A超时后迟到ACK仍能误完成B；host epoch无法补出线身份。超时后冻结该类副作用操作并进入Unknown；状态读取可恢复当前状态知识，但不证明下一旧ACK属于B。没有已证明的迟到寿命上界，固定静默等待或仅重开串口都不足以安全恢复配对；T04保留禁用，后续协议事务号或可证明设备/链路重置后再恢复。

Golden检查见tests/test_contracts.py：固定十六进制输入与PC实际native编解码对照；它只证明PC构帧/CRC和边界helper，**不证明实际FW已修复**。T03已通过真实Dm_ProcessFrame路径验证181/182/192/193响应行为，并导出tests/fixtures/ns5039-get-info.json供T04跨端解析；64位测试机使用窄内存访问接缝，不直接解引用MCU地址。固定测试ID不是ARM或板上身份。
