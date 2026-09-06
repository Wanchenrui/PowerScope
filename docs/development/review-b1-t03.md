# B1 T03 独立审查（进行中）

审查者catalog_t05（T05实现者，但未实现T03）。审查对象FW worktree build/fw-t03，基线3469da8；生产FW/脚本只读，未修改。此文不是最终放行，等待最后diff与ARM实际目标构建结果。

已对照冻结protocol-contract-v1.md逐行审查core.c/h、linker KEEP身份节、构建身份prepare/finalize及目标build脚本。ReadMemory缓冲缩为181，长读先LENGTH不执行memcpy；GetInfo保留94字节前缀并追加PSC1，总174数据/185帧；仅导出实际命令，RESET未置位。uintptr_t变更在ARM 32位保持规则大小和地址语义，九项s_writeRules符号/范围与3469da8完全一致。未改算法或库。新增窄地址接缝默认宏仍为原物理地址转换。

独立反例使用tests/firmware_ns5039/review_driver.c直接include实际core.c及真实wave_codec.c，仅提供HAL/DWT/物理地址翻译，不导入实现者test_core.c。Python独立CRC表oracle与固定线格式期望生成原始帧，校验完整response命令/seq/status/长度/CRC及数据。覆盖181成功满192帧，182/192/193/0 LENGTH；Flash/DTCM/SRAM跨区与32位溢出拒绝；13字节静默、缺CRC字节LENGTH、坏CRC；batch16×8=128成功/17拒绝；sample16×4=64成功/17拒绝/9×8=72拒绝/8×8=64成功；GetInfo精确扩展及17个命令集合、RESET拒绝。另检查原ACL未扩展，以及dirty快照包含未跟踪构建输入、逐hash复核、快照确定性。

真实命令：`.venv/Scripts/python.exe -m pytest tests/test_t03_review.py -q`，2026-09-06，12 passed in 0.65s，exit0。测试夹具自动用build/toolchain/bin/gcc.exe编译独立driver，并链接build/fw-t03真实C。若缺显式worktree/compiler会skip；本次无skip。

当前阶段未发现阻断。尚未执行最终目标ELF/map/bin与manifest实物核验，亦未确认最终build脚本版本。实现者200-check harness结果不替代上述独立反例。串口、带电台架与控制效果均BENCH_PENDING。

## 最终独立结论（2026-09-06）

**T03代码与离线目标构建审查通过；BENCH_PENDING。** 已覆盖最后生产diff及末版生成器，当前无阻断项。上方“进行中”是首轮记录，以下取代该阶段状态。

末版真实构建日志build/t03-target-final.log完成BUILT；Arm GNU Toolchain 12.3.Rel1 GCC12.3.1，text125900/data8784/bss157524。审查者未重新执行耗时全量构建，但读取完成日志并独立核验实物：EM_ARM/32位/小端ELF、KEEP保留.powerscope_build_id位于0x0801de48且恰32字节；四个Flash PT_LOAD逐段与134684字节BIN对应、长度相符；ELF/bin/map三个实物hash均匹配manifest。再次收集当前FW源输入与最终canonical记录完全相等，341输入/1控制静态库、dirty=true，ZIP逐项输入hash由PC核验器交叉验证通过。生成器当前hash8369ec1404c2b2bbb73b73c0b4bbecb9ab9c6219801537077acad8aba6eb8024匹配记录。

最终身份：build ID `ba046c174342118e27927c5eb4af73a051853d66799a9e96e3593a677db48fd8`，manifest SHA256 `3738e8ff3ab53de66f774c393c28a60da9748a11befb4537c3deb77eb5ff44c6`。ELF SHA `5df210946d5780a999bc1f35c4ed5c84193ba716c9d1f9317f2b63b6b9cdd38d`，BIN SHA `f555c0c0ab9f3faf1069289b24ca3772a03fcbb46c88ee7fe17f57e83c690d5b`，MAP SHA `9d13eee8a56da011ba85bf30fe1d920ec48c7235221bacfd7e3ee6df355ce3bf`。实物目录build/t03-identity-final；PC verify_manifest(..., device_build_id=ELF内嵌ID, pack_id='ns5039-v1')返回verified=True/errors=空。这是明确的离线交叉核验，**没有把ELF ID输入当板上ID**。

最后独立向量复跑：
```
$env:POWERSCOPE_TEST_FW='D:/GitHub/PowerScope/build/fw-t03'
$env:POWERSCOPE_TEST_HOST_CC='D:/GitHub/PowerScope/build/toolchain/bin/gcc.exe'
.venv/Scripts/python.exe -m pytest tests/test_t03_review.py -q
```
12 passed in 0.58s，exit0，无skip。独立review测试只通过上述显式输入消费另一个FW项目和host compiler，不复制真实FW生产源进PC仓库；缺输入清楚skip。`git -C build/fw-t03 diff --check` exit0；原FW目录git status输出为空且旧ELF SHA仍80b8ba7c699df7316c1e5d084bd37112e36c589bd9c7d90cd94fea47c0d9f9ec，未覆盖原构建物。

构建边界：目标脚本只写显式FW下powerscope-out，非空目录拒绝覆盖；生成header是唯一预构建写入，Debug现存构建物不改。输入扫描包含未跟踪源、控制库、makefile构建选项，排除生成header/输出目录/ELF/bin/object，身份无自引用循环；dirty快照可追溯。本轮finalize增全Flash load BIN对比后已重新全量构建，不以仅32byte ID匹配替代完整BIN关系。生成器/目标脚本路径无隐式原FW D盘路径。

当前ARM编译警告与设备侧效果按T03 handoff保留，不把构建通过视为台架通过。真实GetInfo身份、串口满载、掉线、ACK与参数回读/控制效果仍需硬件验收。
