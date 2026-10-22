# 架构与数据流

## 三层结构

制作层包含 Python 无损读写器、已有 Studio 工程的隔离副本、本地 WAV、Studio 2.02.22 原生编码、便携解码工具和隔离运行库。游戏运行时不运行这些 Python，也没有外部距离识别服务。

bank 层为 FMOD RIFF/FEV metadata 和分离 assets。metadata 保存事件、仪器、时间线、条件、参数、混音和自动化；assets 保存 WAV 索引、FSB 描述和压缩音频。两个引擎 bank 与三个 master 配套文件成套维护。

运行层由游戏创建原有声音事件并提供 3D 位置、速度、转向、负载等参数。共享播报使用 FMOD 的自动 Distance/Direction 参数。运行层输出依据原 bank 图执行；不是 Python 每隔几秒轮询游戏。

## 构建链

```text
不可改动的成品基线 + 输入合同
       |
       +-> 无损 RIFF 解析/回写证明
       +-> 导出原触发图/事件标注/重复调度
       |
本地三段 WAV -> RMS 匹配/短淡入淡出 -> Studio 原生编码辅助 bank
       |                                           |
       +-------------------------------------------+-> 三段 WAV 记录/新 FSB
       |
限定字段变更：三档条件 + 三条仪器连接 + 三个新增 slot 长度
主混音：两条普通 AI 总线及原生 HASH；敌军：两个停机 fader
       |
组装五个 bank -> 独立白名单差异 -> FSB 原音保持 -> 新音频解码
       |
真实 FMOD 加载/预载/离线输出/回调对照 -> SHA 绑定报告
       |
独立 ZIP + manifest + 测试说明 -> 已授权时事务式部署与回滚
```

## 文件职责

| 模块 | 职责 |
|---|---|
| `bank_format.py` | RIFF chunk、typed array、bus 音量偏移、FSB5 header/sample/name/data 解析；未知字段原样 |
| `build_test_package.py` | 基线哈希、三档拆分、仪器/时间线/参数列表连接、两项停机、WAV/FSB 添加、计数/偏移 |
| `prepare_rebuild_audio.py` | 旧声解码参考、读取本地录音、处理响度、创建三个编码辅助事件/音频元数据 |
| `compile_voice_bank.js` | Studio 脚本，查找 `voice_additions` 并只构建辅助 bank 与 master 依赖 |
| `recover_current_logic.py` | 从真实成品导出原图、条件、72 个父调度和历史名称标注 |
| `runtime_probe.py` | ctypes 调用真实厂商运行库，独立加载五个 bank、预载共享 VOX、运行/释放 |
| `runtime_playback_check.py` | 离线 WAV 输出、3D 位置、参数/快照刺激、声音回调及 DSP 时钟 |
| `runtime_regression.py` | 13 组旧 PCM、三新档、17 边界、72 父调度、移动和混音断言 |
| `verify_test_package.py` | 第二条独立差异检查、原始 FSB 保持、所有 WAV 索引范围、音频/输入哈希 |
| `deploy_verified.ps1` | 报告绑定、游戏关闭、暂存、移动原件、成套安装、失败恢复 |
| `restore_deployment.ps1` | 只还原对应五文件，校验旧/新版本，保留备份 |
| `workspace_paths.py` | 从本地 JSON 解析路径；无硬编码旧 E/F 路径 |

## 为何不用旧工程整体编译

旧目录缺少当前 VOX 接线；历史脚本曾预期 85 组连接，现存旧 XML 不能匹配。直接完整构建会丢掉当前工作功能。手工维护以成品为基线，保留不理解的字节，再做最小且可审查差异。Studio 辅助项目只负责新声音编码和已核对的主混音，不能被称为完整恢复原项目。

主混音有一个很强的校验：隔离旧主混音原生重编译的基线与初始成品 `masterbank.bank` SHA 完全相同。修改后仅两条普通 AI GBSS 音量和对应两个 HASH 值变化。当前本地录音修订没有再次改变任何 mixer。

## 保持边界

原两个 FSB 整体不动，3,426 个压缩样本保持；只添加第三 FSB。既有事件名称/GUID、曲线、优先级、父时间线均不改。新 GUID 固定由 UUID5 命名空间生成。新录音不涉及枪炮或飞机。共用 FX 未加入敌友条件猜测。
