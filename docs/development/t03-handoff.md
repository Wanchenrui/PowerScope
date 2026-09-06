# T03 实际 NS5039 协议与构建身份交接

状态：CODE_VERIFIED；catalog_t05最终独立审查通过，无未关闭阻断，代码冻结待协调者集成，BENCH_PENDING。未提交、未推送、未开串口或烧录。

基线：PC cdfc83029c0233e4fea30b59f474c99a50612a03；FW 3469da8eaeb2b5657381df49817e350f35964c15。唯一FW修改树 `D:/GitHub/PowerScope/build/fw-t03`，分支 `plan/t03-protocol-identity`；原树 `D:/GitHub/newns800RT50xx` 始终clean，原ELF SHA256仍为 `80b8ba7c699df7316c1e5d084bd37112e36c589bd9c7d90cd94fea47c0d9f9ec`。

## 修改与消费接口

FW只改 `user/source/debug_monitor_core.c`、`user/include/debug_monitor_core.h`、`ns800rt/startup/ns800rt5039_eflash.ld`。生成头 `user/include/powerscope_build_id.h` 是构建产物，不提交；没有生成头时构建明确失败，必须先运行身份prepare/target脚本。未修改uart_msg_port、ACL条目/范围、DMA、功率算法/保护、PI注释或静态库。

ReadMemory容量从响应192减11推导为181，编译期断言；182..193在读取前明确LENGTH。GetInfo保留0..93，追加固定PSC1 80字节，174 payload/185 frame。支持请求命令集合为01..08、0C..0E、20..23、25..26；RESET、STREAM_DATA、WAVE_DATA等非支持请求不置位。`.powerscope_build_id` KEEP放在.text之后，向量表仍在08000000，32原始ID字节由GetInfo读取。

`g_dm_response_drops` 是volatile u32，仅后台响应队列满时自增，初始化清零、溢出按u32回绕；ISR不写，不是饱和计数/原子跨线程累计。通过匹配ELF符号读出，不扩展冻结前缀。已有s_txBusyRetries、ring drops及UART high/low overflow保留；本轮没有重写DMA队列。

主机窄接缝 `DM_MEMORY_POINTER` 将物理地址转换到测试内存；生产默认仍直接uintptr_t转换。ACL规则地址内部字段改uintptr_t使64位主机可编译静态真实符号地址，ARM上仍32位，匹配时仍u32；没有新增合法地址。测试使用真实core.c入口与wave_codec.c、真实inv/pi/urms头；只替代DWT/DMB、emath标量typedef、物理地址和UART/control hooks。控制hook调用会abort，不能冒称控制效果。

PC交付：`scripts/ns5039-build-identity.py`、`scripts/ns5039-build-target.py`、`scripts/ns5039-test-host.ps1`、`tests/firmware_ns5039/*`、`tests/fixtures/ns5039-get-info.json`、本文及授权的协议文档状态更新。固定GetInfo fixture是真实C host运行结果，测试ID000102..1f不是ARM构建ID。

## manifest schema 1（T03唯一生产，T05核验）

JSON编码UTF-8。`build_id=SHA256(json.dumps(build_inputs, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8'))`。没有时间或本机绝对路径进入canonical输入。所有sha256为64位小写hex，commit为40位hex。

`build_inputs`字段：schema_version int=1；model string=`NS800RT5039`；fw_commit string；dirty bool；inputs array `{path:string,sha256:string}`按相对POSIX路径排序；toolchain object `{version:string}`保存编译器实际--version；compile_options/link_options string arrays保存规范化斜线的实际make recipe（含ABI、宏和链接选项）；static_libraries array同inputs记录结构；identity_generator_sha256 string绑定生成器本身。所有源、头、链接脚本、make/IDE输入、库和未跟踪输入均快照；排除生成头、ELF/bin/map/object等产物、.git、powerscope-out和powerscope-identity输出目录。dirty不仅是标志：source.zip保存全部输入实际字节，包含未提交改动和未跟踪构建源。

顶层字段：schema_version int=1；status string（prepare仅BUILD_PENDING，finalize成功为BUILT）；model/device_pack_version/pc_commit/fw_commit/build_id strings（pack默认`1`）；build_inputs上述object；source_snapshot `{path,sha256}`；static_libraries同canonical列表；memory_regions array `{name:string,start:int,end:int}`为半开区间；最终额外artifacts object，包含elf/bin/map各 `{path,sha256}`。顶层path相对manifest目录，canonical inputs路径相对FW根。最终目录自包含ELF/bin/map、库和source.zip。manifest自身hash只由PC核验器计算，不回填ID输入。

prepare生成input-record.json及source.zip和FW生成头；缺编译器可prepare记录UNAVAILABLE，但不能finalize。finalize重算所有输入，核对快照hash、ARM ELF架构/32字节section ID，并从所有Flash PT_LOAD段重建完整BIN逐字节比较，再写manifest。产物核验不等于设备认证；实际板上ID相等尚未测。

## 可复跑命令与实际结果（2026-09-06）

PowerShell主机路径相对PC根：

```powershell
./scripts/ns5039-test-host.ps1 -Firmware build/fw-t03 -Compiler build/toolchain/bin/gcc.exe
./.venv/Scripts/python.exe -m pytest tests/firmware_ns5039/test_identity.py -q -p no:cacheprovider
./.venv/Scripts/python.exe scripts/ns5039-build-target.py --fw build/fw-t03 --cc build/t03-arm-toolchain/arm-gnu-toolchain-12.3.rel1-mingw-w64-i686-arm-none-eabi/bin/arm-none-eabi-gcc.exe --make build/toolchain/bin/mingw32-make.exe --out build/t03-identity-final
```

主机真实C **229 checks passed / exit0**，日志`build/t03-host-final.log`。覆盖181成功、182..193读取前拒绝、零长、截断、CRC、三内存区跨界/32位溢出、batch16=128/17拒绝、sample16/17与64/>64、对齐、临时配置不污染、ACK周期、ACL有限/越界/scratch、response满/drop/retry、采样ring满，以及PSC1帧固定向量。唯一降为非error的warning是原有Dm_BuildRecorderData的unused-but-set-variable，不改旧业务。

身份canonical与dirty/untracked快照独立测试 **1 passed / exit0**，日志`build/t03-identity-tests-final.log`。首次C严格Werror因上述既有警告exit1，首次目标编译链接成功但manifest阶段因Windows默认GBK读取UTF8失败exit1，保留`build/t03-target.log`；已修显式UTF8。第二次成功v2用于PC首次跨端核验，最终只规范新增行尾并加强完整BIN匹配后第三次完整重建成功。

ARM最终 **全量编译/链接/objcopy/manifest exit0**，日志`build/t03-target-final.log`；目标输出在FW/powerscope-out，已有输出时脚本拒绝覆盖（重新运行请使用新工作树或先将该专属输出移到另一个已核实目录，不能覆盖原Debug）。旧两次输出保留PC build/t03-target-first、t03-target-second。

工具链官方Arm 12.3.Rel1 GCC12.3.1 20230626，与原ELF主编译器.comment一致；原库另含10.3.1，未替换。ZIP 336539068字节，官方SHA256 `d52888bf59c5262ebf3e6b19b9f9e6270ecb60fd218cf81a4e793946e805a654`已匹配（`build/t03-arm-toolchain-verified.log`）。[官方下载](https://developer.arm.com/-/media/Files/downloads/gnu/12.3.rel1/binrel/arm-gnu-toolchain-12.3.rel1-mingw-w64-i686-arm-none-eabi.zip)；对应`.zip.sha256asc`官方校验记录在build。Windows解压可选HTML文档出现大小写同名冲突，编译器/runtime目录用zipfile完整提取成功；没有系统安装/PATH修改。

最终产物目录 `build/t03-identity-final`，manifest.json；ARM ID `ba046c174342118e27927c5eb4af73a051853d66799a9e96e3593a677db48fd8`；ELF SHA256 `5df210946d5780a999bc1f35c4ed5c84193ba716c9d1f9317f2b63b6b9cdd38d`；BIN `f555c0c0ab9f3faf1069289b24ca3772a03fcbb46c88ee7fe17f57e83c690d5b`。text125900/data8784/bss157524；`.powerscope_build_id`地址0801de48、32字节。`.text`08000000/122440、DTCM .data20000400/8048+.bss20002370/15276、SRAM .srambss20100000/142240；map和`build/t03-arm-sections-final.log`给出完整分布，未发生链接溢出。

FW `git diff --check` exit0；原FW clean及旧ELF hash未变。最终产物交T05核验器以ELF嵌入ID作为离线DeviceIdentity输入，不能称板上测量。独审结论见`review-b1-t03.md`：最终源341 inputs匹配、12独立C向量通过，PC离线核验verified=True，manifest SHA256 `3738e8ff...`（完整值见审查记录），无未关闭阻断，非实现者自审。

## 保留边界与释放

没有真实UART DMA队列时序/台架/升级/功率效果验证，BENCH_PENDING。主机UART busy只能证明core对队列反馈的处理，不能证明DMA底层并发；ISR主机循环不能证明40kHz预算。构建产物尚绑定未提交dirty源快照，最终FW提交后若需要clean release ID必须重新prepare/重建并再核验；提交不自动改变现有产物身份。

FW上述3生产文件、PC脚本/专项测试现冻结供独审和协调者集成；生成头、powerscope-out、官方工具链、日志与二进制不提交。允许协调者提交PC项目分支及FW独立分支，双仓库分别记录兼容组合。后续修复仍由实现者处理。
