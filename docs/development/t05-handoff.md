# T05 参数目录与运行接入交接

状态：实现完成，等待独立审查；未commit/push。PC基线cdfc830，FW源只读3469da8。

文件：config/device_pack.py（最小注册/五状态/manifest核验），config/device_profile.py与NS/ESS YAML，debug/elf_parser.py可信DWARF来源及内容hash缓存，ui/main_window.py目录运行消费（T04生命周期改动共存），ui/power_main_window.py仅升级epoch失效/重握手，tests/test_device_pack.py、tests/test_device_config.py，architecture/ns5039-parameter-catalog.md、development/t05-permission-diff.json及本文。core/contracts.py未改、FW未改。F8无需另建权限缓存，公共elf/loaded事件驱动目录；真实控制继续G0拒绝。

公开接口：DeviceCatalog(profile,symbols,identity=None)，parameters、diagnostics、report()、subscription_allowed(alias)、invalidate()；verify_manifest(path,elf_path,device_build_id,pack_id)返回Verification(verified,build_id,manifest_sha256,errors)。subscription是本地可信类型候选，readable需匹配构建物但实际读取仍以响应为证据，ACL只表示静态8项；writable/tunable都保持False、effect为unknown。旧目录引用在epoch失效时清空，不保留授权。profile.manifest_file为空时受限运行，不弹确认、不自称身份匹配。

manifest schema生产归T03，PC只消费schema_version=1/status=BUILT、model、device_pack_version='1'、build_id、build_inputs、artifacts elf/bin、static_libraries、dirty source_snapshot。核验ID摘要/设备ID/ELF内嵌ID与所有构建物hash，不把任意hash自声明作为设备匹配。畸形JSON/缺字段/无效ELF返回明确拒绝。

真实命令（PowerShell）：
```
$env:QT_QPA_PLATFORM='offscreen'
$env:POWERSCOPE_TEST_ELF='D:/GitHub/newns800RT50xx/Debug/C01_2in1_20260821_ongridStable.elf'
.venv/Scripts/python.exe -m pytest tests/test_device_pack.py tests/test_elf_parser.py tests/test_device_config.py tests/test_ns800rt_tuning_profile.py tests/test_profile_hot_reload.py tests/test_profile_elf_autoload.py -q
```
结果：2026-09-06，43 passed in 8.02s，exit0。首次运行因ESS模板更名与旧测试期望不符1 failed/34 passed exit1，更新该期望后通过。专项包含独立SHA绑定18地址夹具、准确8/10 ACL、电流不可整定、未知类型/改符号拒绝、ESS/旧YAML隔离、pllPhase禁订阅、主窗口实际接入、失效后旧目录清空、完整合成ELF内嵌ID核验及逐ELF/bin/lib/snapshot篡改、未知ID/版本、截断ELF、同路径同mtime内容变更重解析。

报告：docs/development/t05-permission-diff.json，由现存SHA80b8... ELF的ELFParser及DeviceCatalog.report()生成，原始拷贝build/t05-permission-diff.json。18 resolved、8 ACL、10拒写、readable/writable/tunable均false；未知effect不冒充inactive实测。

未运行：全套由唯一集成审查者执行；无ARM构建、串口、真实manifest生成产物/设备ID匹配、台架参数回读或控制效果测量。合成manifest测试不是实际固件构建证据。BENCH_PENDING。独立审查结论待session_t04，不自最终审。文件实现交付可供审查，修复仍由本实现者负责。

独审修复更新：T04以真实ELF复现queued elf/loaded跨apply_profile回填旧311符号（P1，1 failed exit1）。已修复：ElfLoadedEvent仅增加兼容默认None的load_token字段，inspector每次load/profile使用唯一object token；main只接受当前inspector token，PowerMain仅super接受后才转MSG ELF。加载开始用elf_loading同步signal失效main路径/符号/epoch，关闭旧parser并清watch/树；失败不保留旧解析。涉及追加core/event_bus.py和variable_inspector_view.py（已获协调者授权，保留T04块读改动）。公开新事件语义已通知T04/F。

额外加固dirty ZIP快照逐输入名称/hash核验，防止仅自声明快照文件hash却内容不对应构建输入。tests/test_symbol_search.py缓存夹具由phantom.elf迁移真实最小ELF，明确同mtime内容变化仍重新解析。

复跑：device_pack/t05_review/profile_elf_autoload/profile_hot_reload/symbol_search五组38 passed in 7.00s exit0（此后仅补加载失败关闭旧parser/清watch树，待独审重跑）。此前device_pack/symbol_search/t03_review三组45 passed in 5.45s exit0；device_pack新增dirty快照反例后13 passed。所有命令使用同前offscreen及显式旧ELF路径。

最终实现复跑补记：device_pack/elf_parser/symbol_search/t05_review四组51 passed in 8.29s exit0。ELF缓存删除未用mtime方法并改名_cache_digest；缺DWARF成员offset保持未知，bitfield不作为独立原始标量，union有明确0偏移。T05生产已冻结交T04独审。

统一全套首轮历史：766 passed / 8 failed in 46.29s，exit1，无skip，日志build/b1-final-pytest.log。其中T05相关6失败位于main_window_ns800rt与wave_ui_v2：旧假ElfVariable没有可信DWARF来源、直接塞_symbols未生成运行目录、ACK测试未设置已协商采样能力。经协调者授权仅迁移这两测试文件；假解析输出加dwarf_verified并通过当前load_token真实_on_elf_loaded入口生成目录，假串口只补16项/64字节能力前置。保留频道/慢流隔离/双ACK门禁/NACK与128KiB触发比例clamp全部原断言；安全监控夹具同样补可信来源，避免因所有符号未知而偶然通过。无生产变更。

实际命令：`$env:QT_QPA_PLATFORM='offscreen'; .venv/Scripts/python.exe -m pytest tests/test_main_window_ns800rt.py tests/test_wave_ui_v2.py -q`。21 passed in 1.50s，exit0。已交session_t04独立复核，未自行再跑全套。

独立T05结论见[review-b1-t05.md](review-b1-t05.md)，T03最终离线产物审查见[review-b1-t03.md](review-b1-t03.md)。最终FW产物manifest SHA3738e8ff3ab53de66f774c393c28a60da9748a11befb4537c3deb77eb5ff44c6、build ID ba046c174342118e27927c5eb4af73a051853d66799a9e96e3593a677db48fd8；ELF SHA5df210946d5780a999bc1f35c4ed5c84193ba716c9d1f9317f2b63b6b9cdd38d，BIN SHA f555c0c0ab9f3faf1069289b24ca3772a03fcbb46c88ee7fe17f57e83c690d5b。PC跨端核验使用离线ELF内嵌ID，不是板上身份确认。

最终集成结论（2026-09-06）：本轮T05已由session_t04独立审查并关闭旧ELF排队污染等阻断，状态更新为CODE_VERIFIED；上文“待独审”等保留为历史。统一软件验收774 passed in44.89s、exit0、无skip，末版ARM构建物与PC核验器离线一致性通过；不构成真实板上身份或功率效果验证，硬件仍BENCH_PENDING。最终提交组合、构建物hash、提交前dirty manifest说明与下批依赖见[B1协调记录](b1-coordination.md)，独审见[review-b1-t05.md](review-b1-t05.md)。
