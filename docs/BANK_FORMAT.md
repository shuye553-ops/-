# 已验证的 bank 格式与易错点

这是维护所需的有限解码合同，不是 FMOD 私有格式的完整规范。

## 容器与保持

文件开头为小端 `RIFF`，类型 `FEV `；块头是 4-byte tag + uint32 payload 长度，奇数 payload 后有 1-byte padding。`LIST` 在 payload 前四字节保存 kind，其余为子块。顶层包含 `FMT `、`LIST/PROJ`，资产 bank 还有 `SND `。原始 trailer、未知 payload 和 padding 均保留。

任何基线读入后，`Bank.encode()` 必须与原文件完全相同；失败立即停下。不要将不可理解的字段设为零、排序全部子块、删除“无用” section 或批量替换任意 GUID 字节。

已测 FMT payload 对应 142/140；版本字段相同不等于所有格式语义已理解。

## Typed array

在本项目已用位置：uint16 tag=`2*count+1`；空数组仅 ushort 1。非空后接 ushort stride，再接 count×stride 字节。数量不超过 32,767。按实际 section 格式读取，不能把任意 ushort 当作该数组。

GUID 用 UUID `bytes_le` 存储。固定新增 ID 使用 UUID5 命名空间 `{829787ec-818a-4d10-afc2-67439ab1e8e0}` 与稳定名称，如 `dist_120m/instrument`、`dist_120m/audio`。

## WAV 索引：曾导致运行失败的字段

每个 WAV payload 为 30 字节：

| 偏移 | 类型 | 含义 |
|---|---|---|
| 0 | 16 bytes | wave GUID |
| 16 | uint16 | 已测类型值 12 |
| 18 | uint32 | 该 bank 内的 FSB 索引 |
| 22 | uint32 | FSB 内样本索引 |
| 26 | uint32 | 既有尾字段，保持 |

正确 Python 读取为 `struct.unpack_from('<HIII', payload, 16)`。把它误读成 `<IHII>` 时，FSB0 看似正常，FSB1 的低位会混入类型；把新增 index=2 写偏移20会变成 131072，触发运行库断言 `bankIndex < mSoundBankOffsets.count()`。静态 RIFF 可读、vgmstream 可解码仍可能漏掉这一错误，因此必须做真实预载。

校验所有原/新 WAV：FSB 索引小于 FSB 数量，sample 索引小于对应样本数量。新三条使用第三 FSB（索引2）。

## FSB5 与 SNDH

FSB5 header=60 bytes，后接 sample headers、name table 和 data。每个 sample 基本 header 为 uint64：低位标记扩展；频率 index、声道、按32-byte单位的数据偏移、frame_count 均按代码读取。扩展块不可丢弃；mode15为所测 Vorbis，mode16为所测 FADPCM。

原资产 bank 两个 FSB：3,197 + 229 = 3,426 样本。按整个原 FSB blob 比较 SHA 和字节，不能仅比较解码波形或样本名。新声音由原生 Studio 编为第三 FSB。

`SNDH` 是 stride8 的 typed array，每项 `<II>` 为 FSB 的**文件绝对偏移和完整大小**。每个 FSB 物理起点按32字节对齐；新增 metadata 改变前置长度时，必须重算所有 SNDH 偏移与 RIFF/section 大小。单独每个 SND 块可含对齐零填充，padding 不算 FSB 长度。

## 仪器和连接

`WAIS` 记录内 `WAIB` 前16字节仪器ID、后16字节waveID；单 Distance 条件的所测 `INST` 长162，末尾8字节是 min/max float32。前述结构只对已核对模板使用；不能推广到复合方向条件。

共享 VOX 的 TLNB：GUID 后先空数组，再是15个 stride24 slot；slot为 instrumentGUID16 + startTicks uint32 + lengthTicks uint32。新增3个后为18。保持15个旧 slot 原字节，只新增三条长度，start=1.6秒。

对应 PMLB 前32字节后是 stride16 的模块ID列表，由15变18，原头尾字节保持。更新 WAIS/WAVS 的 LCNT。仪器、时间线、参数列表三个位置必须同时接入，不能只把 WAV 塞进 assets。

BUS 音量：payload偏移8后消费两个 typed array，再核对 ushort8，随后的float为音量。不要按所有BUS同一固定偏移写。GBSB/IBSB 等输出 GUID 的已核对位置是18:34；snapshot/master记录类型需分别判断。

## HASH 边界

HASH entry stride20，GUID16+4-byte opaque tag。完整语义尚未解码。原始事件标签保留；两条主混音值由已验证的原生编译结果提供；三新wave值来自其原生声音构建。不能把任意 CRC32/时间戳填进去。公开复刻合同可记录原生主混音两条 tag 的精确前后值，并以完整输出 SHA 证明重放等效。

字段解释必须以原包、代码断言、真实运行库和当前报告交叉验证；反汇编或猜测不自动成为兼容保证。
