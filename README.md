# 战争雷霆 EchoContact VOX 制作与复刻源码

中文纯文本交接仓库。保留既有语音播报与节奏，补120/160/200米、普通AI耳机发动机/履带静音及两条敌军停机声音漏项。这里提供核心制作代码、格式说明、输入合同、验证和回滚流程，供人或Agent审查并继续维护。

**先读 [AGENTS.md](AGENTS.md) 和 [复刻说明](docs/REPRODUCE.md)。本仓库不包含原成品bank、录音、FMOD软件、DLL或完整第三方工程。Git clone之后仍需自备对应输入。** 本机完整制作资料已迁到 `F:\战争雷霆语音包制作文件`；GitHub是可审查的文本发布快照。

<img width="2560" height="1480" alt="volume-distance-comparison" src="https://github.com/user-attachments/assets/a109d797-1547-4385-80b2-205bf184a9fc" />

图1-1 战争雷霆官方引擎音量衰减曲线与 EchoContact v1.2.1 的对比（原仓库配图）。

## 给Agent的任务起点

```text
请先阅读AGENTS.md、docs/ARCHITECTURE.md、docs/LOGIC.md、docs/BANK_FORMAT.md和docs/REPRODUCE.md。
先核对contracts中的基线合同与本地输入；没有指定成品基线时报告缺项，不能编译旧fspro冒充当前成品。
有合法本地输入后运行bootstrap_workspace.py和reproduce.py，生成独立测试包；所有PASS必须绑定本轮SHA256。
保留原14段、八方向、72父事件、2952触发实例、优先级和曲线。保留共用悬挂；残留友军移动声尚无现场调用证据。
根据我的具体新请求修改最小范围，不要自行替换游戏或生成TTS。
```

## 阅读入口

- [架构与事实来源](docs/ARCHITECTURE.md)：成品bank、参考Studio工程、脚本各自的职责。
- [播报与敌友逻辑](docs/LOGIC.md)：旧调度、新阈值、耳机Send/Return、共享FX。
- [二进制格式与补丁白名单](docs/BANK_FORMAT.md)：RIFF、TLNB/PMLB、WAV、FSB、HASH及已踩过的坑。
- [完整复刻步骤](docs/REPRODUCE.md)：版本、输入、路径、原生编码、构建、真实运行库验收。
- [验收边界](docs/VALIDATION.md)、[部署与回滚](docs/DEPLOYMENT.md)、[移动残留调查](docs/MOVEMENT_RESIDUAL.md)。
- [当前本机状态](docs/CURRENT_LOCAL_STATUS.md)：历史部署和用户反馈，不等于新复刻包实机通过。
- [单文件超详细文本](AGENT_REPRODUCTION_FULL.txt)：上述说明和全部核心代码，便于整体交给Agent。
- [原仓库README](docs/LEGACY_README.md)：保留历史介绍，现行技术事实以上述文件为准。

## 最小使用方式

Windows x64，Python3.11+与numpy，FMOD Studio2.02.22、vgmstream及匹配FMOD2.02运行库。不要全局安装依赖；自行配置独立环境。实际执行参数见复刻说明。

```powershell
python -B scripts/bootstrap_workspace.py --help
python -B scripts/reproduce.py --check-only
python -B scripts/reproduce.py
```

bootstrap先验证输入，再把参考工程复制到本工作区；reproduce不会写游戏目录。输出在test-package和releases。代码并不恢复遗失的完整Studio播报XML，维护依据是原成品中已存在的真实图。旧曲线、父调度、压缩样本按字节保留，未知字段不猜测。

用户曾实测前版可以正常工作、豹2A7V友军静音有效。后来仅将新增三段换为本地录音，静态、解码和离线运行库回归通过；不能据此宣称所有车型、所有游戏场景已经验收。

## 目录

scripts为公开维护源码；contracts为基线/录音/当前输出指纹与两条原生master差异；docs为设计与操作说明；source仅含包说明模板。所有二进制输入、自动图导出和临时报告均被.gitignore排除。原始素材和第三方工具的使用与再分发遵循其各自许可；此提交不为它们重新授权。
