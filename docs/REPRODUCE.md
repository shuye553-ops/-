# 从纯文本仓库复刻

## 复刻的确切含义

仓库提供可审查的维护算法、连接逻辑、输入规格和验证流程。原声音、当前工作成品、商业工具不在文本提交内。**Git clone 本身不会恢复没有提供的 bank、录音或原始工程**；Agent 先核对输入，缺少时报告缺项，不可拿 Gaijin 原版或空 XML 替代已含14段播报的特定基线。

本机资料已全部集中到根目录，可以直接从 `maintenance/` 接手。其他机器需要准备以下输入，再运行公开目录的 bootstrap/reproduce。

## 输入清单

1. 与 `contracts/baseline_manifest.json` 一致的初始成品，至少五个核心 bank。其 tanks 已有原14声音、共享 VOX、72父调度；不是游戏原始声音 bank，也不是现在安装的二次更新包。
2. 用户自己的 `dist_120m.wav`、`dist_160m.wav`、`dist_200m.wav`，24kHz、单声道、16bit PCM；本次原文件长度分别23040、21120、24960帧。可换自有录音，但应单独记录新输入指纹并重新验收。
3. FMOD Studio 2.02.22，提供 `fmodstudiocl.exe` 及其完整相邻依赖；不要只拷贝exe。
4. 可加载的官方风格 Studio 参考工程，包含 `.fspro`、Metadata、被引用 Assets 和 Abrams 停机模板 `{95513cdf-5279-45f2-9f85-0a1bd553c74f}.xml`。本地直接用集中目录现成隔离副本。公开复刻需自行取得参考工程；它只用于新声音编码，不被当作恢复的 VOX 原图。
5. 便携 vgmstream CLI，解码原包参考和新 bank 检查。当前使用 r2117，来源与哈希见本地 tools provenance。
6. 可用 FMOD 2.02 系列 x64 Core/Studio 运行库，包含 release/logging DLL 和匹配的 `fmod_common.h`。当前实测2.02.14（版本整数 `0x00020214`，不是十进制2.02.20）。这些库只供离线验收，不复制进游戏。
7. Python 3.11+（需要 `hashlib.file_digest`）与 numpy。当前 numpy2.5.2。使用任务私有环境或已有环境，不全局安装包。

公共参考地址：

- 官方参考工程：<https://github.com/GaijinEntertainment/fmod_studio_warthunder_for_modders>
- Studio/SDK：<https://www.fmod.com/download>
- vgmstream：<https://github.com/vgmstream/vgmstream/releases>
- 当前验收运行库来源记录指向 ejoy/ant 固定提交的 vendor 文件，不通过此仓库二次发布DLL。

公开 `contracts/runtime_provenance.json` 给出运行库固定提交、逐文件 URL 和 SHA；`contracts/tool_fingerprints.json` 给出实际 CLI 与头文件指纹。`contracts/announcement_schedule.json` 列出72个父事件所属的六类序列化时间表，原2952实例由输入bank和源码逐条核验。零时间slot不应被解释为立即可听报数，运行时仍受实际连接和条件控制。

## Bootstrap

从仓库根目录运行 `scripts/bootstrap_workspace.py --help`。提供基线、录音、Studio参考工程、Studio CLI、vgmstream和运行库目录，工具写入本地 `workspace.local.json`，建立受保护的 `baseline/package` 与初始manifest。输入合同不符会停止，不会默默接受另一版本。

```powershell
python -B scripts/bootstrap_workspace.py `
  --baseline 'X:\inputs\original-package' `
  --audio 'X:\inputs\audio' `
  --reference 'X:\reference\sounds-project' `
  --fmod 'X:\tools\FMOD Studio 2.02.22\fmodstudiocl.exe' `
  --vgmstream 'X:\tools\vgmstream-cli.exe' `
  --runtime 'X:\tools\runtime-2.02'

python -B scripts/reproduce.py --check-only
python -B scripts/reproduce.py
```

`--check-only` 不编译，也不替换声音，只生成输入检查报告。bootstrap拒绝覆盖已有本地配置或工作参考目录；若中断，先检查已产生文件，再选择一个新的干净工作区，不把初始化当作强制清理命令。原始输入复制到工作区仅是跨机器复刻的正常隔离操作；本机归档的原资料已经实际移动到集中目录。

参考工程作为输入，工具会建立工作副本后再添加三个编码辅助事件；不会就地改变传入的参考项目。不要把已验证游戏安装目录设成 baseline 工作写入目录。

bootstrap不复制参考工程的 `Scripts/`。Studio会在载入项目时执行该目录顶层脚本；旧资料中发现过无菜单保护、顶层直接遍历并改写敌军事件的脚本，会拖慢或干扰编码。公开入口只显式执行本仓库 `compile_voice_bank.js`，项目素材中的脚本不能作为接手指令自动运行。

没有配置游戏路径时，只构建和验证独立包。配置了游戏目录并不等于获准部署；部署是独立操作，不在 reproduce 内自动执行。

## 构建顺序

1. 校验基线哈希与本地配置，保存本轮输入指纹。
2. 根据公开文本合同重放两个主混音 fader/tag 的原生已测差异，验证 master输出完整SHA；这只适用于指定基线。或在本地现成工程使用已保存的原生 master输入。
3. 解码原14段作为响度参考，读取三段本地录音，按既有RMS规则处理，不改变帧数；保存原录音副本/哈希。
4. 给参考项目写入三个独立辅助事件与音频元数据，只构建 `voice_additions` 和master依赖，取原生新增音频资产。辅助事件不是游戏运行的新入口。
5. 导出当前成品图与历史事件名标注，再执行受限 bank 更新。旧两个FSB保持，第三个FSB附加。
6. 运行真实加载、预载、离线回归、独立结构/解码验证；只有绑定当前输出SHA的PASS有效。
7. 生成 `test-package/`、manifest、说明和ZIP，校验ZIP内每个bank的SHA。

若CLI已写出 `VOICE_BANK_BUILD_SUCCESS=true` 且结束日志，但进程清理不退出，可以只终止本次创建的CLI进程；必须先检查日志和输出并继续运行真实加载验收，不把进程非零退出当作未经说明的成功。

入口将各步骤的stdout/stderr保存在 `reports/reproduce-*.log`，原生过程保存在 `reports/native-reproduction.log` 和隔离profile日志。失败会停止后续步骤；先检查出错步骤日志，修复输入/兼容问题再运行，不修改PASS文本绕过断言。`rebuild_test.ps1`只适用于原生输入已经准备好的工作区，不包含新声音编码；完整从零流程使用 `reproduce.py`。

## 可复刻与不应承诺的内容

2026-10-22已进行独立演练：从公开代码和自备输入初始化，完成编码、五bank构建、真实运行库加载、72父调度回归、解码/静态检查与ZIP检查，五个bank的SHA均等于当前本地录音版。公开 `contracts/reproduction_self_test.json` 保存具体指纹。这份历史成功记录不能代替新输入或新代码的本轮验收，也不表示重新进行过游戏现场测试。

相同基线、处理后声音和原生输入会生成相同受限图；原事件、样本保持证明可以复查。不同编码器补丁、压缩设置或numpy实现可能改变新FSB字节；不能仅靠“可播放”宣称二进制完全相同。当前部署指纹见 PROJECT；算法、输入和行为验收合同则用于判断移植是否等效。

没有游戏现场、具体车型和调用记录时，不宣称残留声根因或所有坦克实机覆盖完成。发现格式、输入或路径不匹配，先停在独立产物阶段，保留日志。
